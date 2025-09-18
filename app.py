import os, re, json, traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from flask import (
    Flask, request, render_template, redirect, session, url_for, flash, jsonify
)
from geotext import GeoText
import pycountry
from werkzeug.middleware.proxy_fix import ProxyFix
from oauth_gcal import begin_auth, finish_auth, require_gcal, build_service, health

load_dotenv()

# ----- Date parsing -----------------------------------------------------------
try:
    from dateparser import parse as _parse_date
except Exception:
    from dateutil import parser as _du_parser
    _parse_date = _du_parser.parse

# ----- Base paths & app setup -------------------------------------------------
BASE = Path(__file__).parent.resolve()
DATA_DIR = BASE / "scheduled_data"; DATA_DIR.mkdir(exist_ok=True)
USERS = BASE / "users.json"

app = Flask(__name__, template_folder=str(BASE), static_folder=str(BASE))
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev_secret_change_me")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["PREFERRED_URL_SCHEME"] = "https"
app.config.update(
    SESSION_COOKIE_SECURE=True,
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ----- Regex helpers ----------------------------------------------------------
# Dates anywhere like "Meet mom on Sep 21" (month abbrev + day)
DATE_ANY_RE = re.compile(r"(?:\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})\b)", re.I)
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DATE_PREFIX_RE = re.compile(r"^\s*(?:(" + "|".join(MONTHS) + r")\.?)\s+(\d{1,2})\b", re.I)
TIME_ANY_RE   = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)
TIME_START_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)
GOAL_RE       = re.compile(r"^\s*(Goal:|To\s)\b", re.I)
TRAVEL_KEYWORDS = re.compile(r"\b(flight|fly|arrive|depart|airport|train|hotel|check-?in|to)\b", re.I)

# ----- File helpers -----------------------------------------------------------
def _safe(email:str)->str: return re.sub(r"[^a-z0-9_.@+-]+","_",email.lower())
def user_file(email:str)->Path: return DATA_DIR / f"{_safe(email)}.txt"
def _default_settings(): return {"travel_enabled": False, "time_format": "12h"}
def load_users(): return json.loads(USERS.read_text()) if USERS.exists() else {}
def save_users(d): USERS.write_text(json.dumps(d, indent=2))

def read_user_blob(email:str):
    p = user_file(email)
    if not p.exists():
        p.write_text(f"SETTINGS:{json.dumps(_default_settings())}\n", encoding="utf-8")
    raw = p.read_text(encoding="utf-8").splitlines()
    if raw and raw[0].startswith("SETTINGS:"):
        try:
            settings = json.loads(raw[0][9:])
        except Exception:
            settings = _default_settings()
            raw[0] = f"SETTINGS:{json.dumps(settings)}"
    else:
        settings = _default_settings()
        raw.insert(0, f"SETTINGS:{json.dumps(settings)}")
    lines = [ln for ln in raw[1:] if ln.strip()]
    return settings, lines

def write_user_blob(email:str, settings:dict, lines:list[str]):
    p = user_file(email)
    header = f"SETTINGS:{json.dumps(settings)}\n"
    body = "\n".join([ln.strip() for ln in lines if ln.strip()])
    p.write_text(header + (body + "\n" if body else ""), encoding="utf-8")

def append_line(email:str, text:str):
    settings, lines = read_user_blob(email); lines.append(text.strip())
    write_user_blob(email, settings, lines)

def reset_user(email:str): write_user_blob(email, _default_settings(), [])

# ----- Parse helpers ----------------------------------------------------------
def parse_time_tuple(line:str):
    m = TIME_START_RE.match(line) or TIME_ANY_RE.search(line)
    if not m: return None
    h = int(m.group(1)); minute = int(m.group(2) or 0); ampm = m.group(3).upper()
    h = 0 if h == 12 else h
    if ampm == "PM": h += 12
    return (h, minute)

def parse_date_prefix(line:str):
    m = DATE_PREFIX_RE.match(line)
    if not m: return None
    mon, day = m.group(1), int(m.group(2))
    try: return _parse_date(f"{mon} {day} {datetime.now().year}")
    except Exception: return None

def is_goal(line:str)->bool: return bool(GOAL_RE.match(line))

def _pycountry_match(word:str)->bool:
    w = word.upper().strip(".,;:!?")
    alias = {"US":"UNITED STATES","USA":"UNITED STATES","UAE":"UNITED ARAB EMIRATES","UK":"UNITED KINGDOM"}
    if w in alias: w = alias[w]
    try: return pycountry.countries.lookup(w) is not None
    except LookupError: return False

def is_travel(line:str)->bool:
    if not parse_date_prefix(line): return False
    tail = DATE_PREFIX_RE.sub("", line).strip(); geo = GeoText(tail)
    has_city_country = bool(geo.cities or geo.countries) or any(_pycountry_match(tok) for tok in tail.split())
    has_keyword = bool(TRAVEL_KEYWORDS.search(tail))
    return has_city_country or has_keyword

def classify(lines:list[str]):
    schedule, dates, other, travel = [], [], [], []
    for ln in lines:
        if is_goal(ln):
            other.append(ln)
            continue

        # Time wins first
        if parse_time_tuple(ln):
            schedule.append(ln)
            continue

        # Date anywhere in the line
        d_any = parse_date_any(ln)
        if d_any:
            # Travel if we detect any location/keyword anywhere in the line
            (travel if has_location_or_travel_kw(ln) else dates).append(ln)
        else:
            other.append(ln)

    # sort using parsed date-any (fallback max)
    schedule.sort(key=lambda x: parse_time_tuple(x) or (99, 99))
    dates.sort(   key=lambda x: parse_date_any(x) or datetime.max)
    travel.sort(  key=lambda x: parse_date_any(x) or datetime.max)
    return schedule, dates, other, travel

def parse_date_any(line:str):
    m = DATE_ANY_RE.search(line)
    if not m: return None
    mon, day = m.group(1), int(m.group(2))
    try: return _parse_date(f"{mon} {day} {datetime.now().year}")
    except Exception: return None

def has_location_or_travel_kw(line:str)->bool:
    geo = GeoText(line)
    has_city_country = bool(geo.cities or geo.countries) or any(_pycountry_match(tok) for tok in line.split())
    has_kw = bool(TRAVEL_KEYWORDS.search(line))
    return has_city_country or has_kw

# ----- Auth routes (login/logout) --------------------------------------------
@app.post("/login")
def login():
    email = request.form.get("email","").strip().lower()
    password = request.form.get("password","").strip()
    if not email or not password:
        flash("Email and password required."); return redirect(url_for("index"))
    users = load_users()
    if email in users and users[email].get("password") != password:
        flash("Incorrect password."); return redirect(url_for("index"))
    users[email] = {"password": password}
    save_users(users); session["email"] = email; flash("Logged in.")
    return redirect(url_for("index"))

@app.post("/logout")
def logout():
    session.clear(); flash("Logged out."); return redirect(url_for("index"))

# ----- Text commands (dictionary-driven) -------------------------------------
def _export_all():
    ct = gcal_export_today().get_json(silent=True) or {}
    cd = gcal_export_dates().get_json(silent=True) or {}
    return {"today": ct, "dates": cd}

# COMMANDS map: lowercased command text -> callable returning Response or dict
COMMANDS = {
    "#import today": lambda: gcal_import_today_to_app(),
    "import today":  lambda: gcal_import_today_to_app(),
    "#export today": lambda: gcal_export_today(),
    "export today":  lambda: gcal_export_today(),
    "#export dates": lambda: gcal_export_dates(),
    "export dates":  lambda: gcal_export_dates(),
    "#export all":   _export_all,
    "export all":    _export_all,
}

# ----- App routes -------------------------------------------------------------
@app.post("/toggle_travel")
def toggle_travel():
    email = session.get("email")
    if not email: flash("Login required."); return redirect(url_for("index"))
    settings, lines = read_user_blob(email)
    settings["travel_enabled"] = not settings.get("travel_enabled", False)
    write_user_blob(email, settings, lines); return redirect(url_for("index"))

@app.post("/add")
def add():
    email = session.get("email")
    if not email:
        flash("Login required."); return redirect(url_for("index"))
    text = request.form.get("add","").strip()
    t = text.lower()

    # Dictionary-driven commands
    if t in COMMANDS:
        resp = COMMANDS[t]()
        if isinstance(resp, dict):  # export all
            ct, cd = resp.get("today", {}), resp.get("dates", {})
            flash(f"Exported {int(ct.get('count',0))} time + {int(cd.get('count',0))} date events.")
        else:
            data = resp.get_json(silent=True) or {}
            if "total" in data:
                flash(f"Imported {int(data.get('total',0))} items from Google.")
            elif "count" in data:
                flash(f"Exported {int(data.get('count',0))} items to Google.")
        return redirect(url_for("index"))

    # Default: just append line
    if text:
        append_line(email, text)
    return redirect(url_for("index"))

@app.post("/reset")
def reset():
    email = session.get("email")
    if not email: flash("Login required."); return redirect(url_for("index"))
    reset_user(email); flash("Data reset."); return redirect(url_for("index"))

@app.get("/status")
def status(): return "up", 200

@app.get("/healthz")
def healthz(): return "ok", 200

@app.get("/debug")
def debug():
    return {"email": session.get("email"),
            "files": [p.name for p in DATA_DIR.glob("*.txt")],
            "users_file": USERS.exists()}

# ----- UI --------------------------------------------------------------------
@app.get("/")
def index():
    email = session.get("email")
    schedule = dates = other = travel = []
    travel_enabled = False
    now_ist = datetime.now().strftime("%Y-%m-%d %H:%M")

    if email:
        settings, lines = read_user_blob(email)
        travel_enabled = settings.get("travel_enabled", False)
        schedule, dates, other, travel = classify(lines)

    return render_template(
        "index.html",
        email=email, schedule=schedule, dates=dates, other=other, travel=travel,
        travel_enabled=travel_enabled, now_ist=now_ist, session_has_gcal=bool(session.get("gcal"))
    )

# ----- Google Calendar --------------------------------------------------------
@app.get("/auth/gcal")
def gcal_auth(): return redirect(begin_auth(request.args.get("next", "/")))

@app.get("/gcal/callback")
def gcal_callback():
    try:
        nxt = finish_auth(request.url)
        return redirect(nxt or url_for("index"))
    except Exception as e:
        tb = traceback.format_exc()
        return f"GCAL CALLBACK ERROR\n{type(e).__name__}: {e}\n\n{tb}", 500

@app.get("/health/gcal")
def gcal_health(): return health()

@app.get("/gcal/next5")
@require_gcal
def gcal_next5():
    svc = build_service()
    events = svc.events().list(calendarId="primary", singleEvents=True,
                               orderBy="startTime", maxResults=5).execute()
    return jsonify(events)

@app.get("/gcal/today")
@require_gcal
def gcal_today():
    from datetime import datetime, timedelta, timezone
    import pytz
    svc = build_service()
    tz = pytz.timezone("Asia/Kolkata")
    start = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    end   = start + timedelta(days=1)
    events = svc.events().list(
        calendarId="primary", singleEvents=True, orderBy="startTime",
        timeMin=start.astimezone(timezone.utc).isoformat(),
        timeMax=end.astimezone(timezone.utc).isoformat(), maxResults=50
    ).execute()
    return jsonify(events)

@app.post("/gcal/add_demo")
@require_gcal
def gcal_add_demo():
    from datetime import datetime, timedelta, timezone
    svc = build_service()
    now = datetime.now(timezone.utc) + timedelta(minutes=10)
    event = {
        "summary": "Scheduled Sync Demo Event",
        "description": "created-by:ScheduledSync",
        "start": {"dateTime": now.isoformat()},
        "end": {"dateTime": (now + timedelta(minutes=30)).isoformat()},
    }
    created = svc.events().insert(calendarId="primary", body=event).execute()
    return jsonify({"created": created.get("htmlLink")})

# Export "today time entries" → 10-minute events at that time (IST → Google), deduped & tagged
@app.post("/gcal/export_today")
@require_gcal
def gcal_export_today():
    from datetime import datetime, timezone, timedelta
    import pytz

    email = session.get("email")
    if not email: return jsonify({"error":"not logged in"}), 401

    settings, lines = read_user_blob(email)
    schedule, _, _, _ = classify(lines)

    tz = pytz.timezone("Asia/Kolkata")
    today = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    start_day_utc = today.astimezone(timezone.utc)
    end_day_utc   = (today + timedelta(days=1)).astimezone(timezone.utc)

    svc = build_service()

    # existing events today (for dedupe): (start_local_minute, summary_lower)
    existing = set()
    existing_resp = svc.events().list(
        calendarId="primary", singleEvents=True, orderBy="startTime",
        timeMin=start_day_utc.isoformat(), timeMax=end_day_utc.isoformat(), maxResults=250
    ).execute()
    for ev in existing_resp.get("items", []):
        start = ev.get("start", {})
        summary = (ev.get("summary") or "").strip().lower()
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(tz)
            key = (dt.replace(second=0, microsecond=0), summary)
            existing.add(key)

    created = []
    for s in schedule[:200]:
        tt = parse_time_tuple(s)
        if not tt: continue
        h, m = tt
        start_local = today.replace(hour=h, minute=m, second=0, microsecond=0)
        end_local   = start_local + timedelta(minutes=10)
        key = (start_local, s.strip().lower())
        if key in existing:
            continue
        start_utc = start_local.astimezone(timezone.utc)
        end_utc   = end_local.astimezone(timezone.utc)
        ev = {
            "summary": s,
            "description": "created-by:ScheduledSync",
            "start": {"dateTime": start_utc.isoformat()},
            "end":   {"dateTime": end_utc.isoformat()},
        }
        created.append(svc.events().insert(calendarId="primary", body=ev).execute())
        existing.add(key)

    return jsonify({"created": [e.get("htmlLink") for e in created], "count": len(created)})

# Export "dates" (and travel) → all-day events, tagged
@app.post("/gcal/export_dates")
@require_gcal
def gcal_export_dates():
    from datetime import timezone
    email = session.get("email")
    if not email: return jsonify({"error":"not logged in"}), 401
    settings, lines = read_user_blob(email)
    _, dates, _, travel = classify(lines)
    svc = build_service()
    created = []

    def _iso_date(dt: datetime) -> str:
        return dt.date().isoformat()

    for txt in (dates + travel)[:200]:
        dt = parse_date_prefix(txt)
        if not dt: continue
        ev = {
            "summary": txt,
            "description": "created-by:ScheduledSync",
            "start": {"date": _iso_date(dt)},
            "end":   {"date": _iso_date(dt)},
        }
        created.append(svc.events().insert(calendarId="primary", body=ev).execute())

    return jsonify({"created": [e.get("htmlLink") for e in created], "count": len(created)})

@app.get("/gcal")
def gcal_root(): return redirect(url_for("gcal_auth"))

@app.get("/_envz")
def _envz():
    m = lambda v: (v[:6]+"…"+v[-4:]) if v and len(v)>12 else str(bool(v))
    return {"GOOGLE_CLIENT_ID": m(os.getenv("GOOGLE_CLIENT_ID")),
            "GOOGLE_CLIENT_SECRET": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
            "GOOGLE_SCOPES": os.getenv("GOOGLE_SCOPES"),
            "REDIRECT_USED": request.host_url.rstrip("/") + "/gcal/callback"}

@app.get("/__routes")
def __routes(): return {"routes":[str(r) for r in app.url_map.iter_rules()]}

# Import today's Google events -> Scheduled (Time/Dates) with dedupe; skip our tagged exports
@app.post("/gcal/import_today_to_app")
@require_gcal
def gcal_import_today_to_app():
    from datetime import datetime, timedelta, timezone
    import pytz

    email = session.get("email")
    if not email: return jsonify({"error": "not logged in"}), 401

    tz = pytz.timezone("Asia/Kolkata")
    start_local = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    end_local   = start_local + timedelta(days=1)

    svc = build_service()
    resp = svc.events().list(
        calendarId="primary", singleEvents=True, orderBy="startTime",
        timeMin=start_local.astimezone(timezone.utc).isoformat(),
        timeMax=end_local.astimezone(timezone.utc).isoformat(),
        maxResults=100,
    ).execute()

    def _fmt_time(dt: datetime) -> str:
        hh = dt.hour % 12 or 12
        mm = f"{dt.minute:02d}"
        ap = "AM" if dt.hour < 12 else "PM"
        return f"{hh:02d}:{mm} {ap}"

    settings, lines = read_user_blob(email)
    existing = set(x.strip().lower() for x in lines if x.strip())

    added_time, added_date = 0, 0
    out_lines = lines[:]

    for ev in resp.get("items", []):
        summary = (ev.get("summary") or "").strip()
        if not summary: continue

        # Skip our own exported events
        desc = (ev.get("description") or "").lower()
        if "created-by:scheduledsync" in desc:
            continue

        start = ev.get("start", {})
        if "dateTime" in start:  # timed
            dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(tz)
            line = f"{_fmt_time(dt)} {summary}"
            key = line.strip().lower()
            if key not in existing:
                out_lines.append(line); existing.add(key); added_time += 1
        elif "date" in start:    # all-day
            d = datetime.fromisoformat(start["date"])
            mon = d.strftime("%b"); day = int(d.strftime("%d"))
            line = f"{mon} {day} {summary}"
            key = line.strip().lower()
            if key not in existing:
                out_lines.append(line); existing.add(key); added_date += 1

    write_user_blob(email, settings, out_lines)
    return jsonify({"imported_time": added_time, "imported_dates": added_date, "total": added_time + added_date})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)