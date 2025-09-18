import os, re, json, traceback
from pathlib import Path
from datetime import datetime, timezone, timedelta
from dotenv import load_dotenv
from flask import Flask, request, render_template, redirect, session, url_for, flash, jsonify
from geotext import GeoText
import pycountry
from werkzeug.middleware.proxy_fix import ProxyFix
# Google helpers
from oauth_gcal import begin_auth, finish_auth, require_gcal, build_service, health as gcal_health_check

load_dotenv()

# ----- Base paths & app setup -------------------------------------------------
BASE = Path(__file__).parent.resolve()
DATA_DIR = BASE / "scheduled_data"; DATA_DIR.mkdir(exist_ok=True)
USERS = BASE / "users.json"

app = Flask(__name__, template_folder=str(BASE), static_folder=str(BASE))
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev_secret_change_me")
app.wsgi_app = ProxyFix(app.wsgi_app, x_proto=1, x_host=1)
app.config["PREFERRED_URL_SCHEME"] = "https"
app.config.update(SESSION_COOKIE_SECURE=True, SESSION_COOKIE_HTTPONLY=True, SESSION_COOKIE_SAMESITE="Lax")

# ----- Date parsing -----------------------------------------------------------
try:
    from dateparser import parse as _parse_date
except Exception:
    from dateutil import parser as _du_parser
    _parse_date = _du_parser.parse

# ----- Regex helpers ----------------------------------------------------------
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DATE_ANY_RE    = re.compile(r"(?:\b(" + "|".join(MONTHS) + r")\.?\s+(\d{1,2})\b)", re.I)
DATE_PREFIX_RE = re.compile(r"^\s*(?:(" + "|".join(MONTHS) + r")\.?)\s+(\d{1,2})\b", re.I)
TIME_ANY_RE    = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)
TIME_START_RE  = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)
GOAL_RE        = re.compile(r"^\s*(Goal:|To\s)\b", re.I)
TRAVEL_KEYWORDS= re.compile(r"\b(flight|fly|arrive|depart|airport|train|hotel|check-?in|to)\b", re.I)
TIME_LEADING_RE= re.compile(r"^\s*\d{1,2}(?::\d{2})?\s*(AM|PM)\b", re.I)

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
            settings = _default_settings(); raw[0] = f"SETTINGS:{json.dumps(settings)}"
    else:
        settings = _default_settings(); raw.insert(0, f"SETTINGS:{json.dumps(settings)}")
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

def has_location_or_travel_kw(line:str)->bool:
    geo = GeoText(line)
    has_city_country = bool(geo.cities or geo.countries) or any(_pycountry_match(tok) for tok in line.split())
    has_kw = bool(TRAVEL_KEYWORDS.search(line))
    return has_city_country or has_kw

def parse_date_any(line:str):
    m = DATE_ANY_RE.search(line)
    if not m: return None
    mon, day = m.group(1), int(m.group(2))
    try: return _parse_date(f"{mon} {day} {datetime.now().year}")
    except Exception: return None

def classify(lines:list[str]):
    schedule, dates, other, travel = [], [], [], []
    for ln in lines:
        if is_goal(ln): other.append(ln); continue
        if parse_time_tuple(ln): schedule.append(ln); continue
        d_any = parse_date_any(ln)
        if d_any:
            (travel if has_location_or_travel_kw(ln) else dates).append(ln)
        else:
            other.append(ln)
    schedule.sort(key=lambda x: parse_time_tuple(x) or (99, 99))
    dates.sort(   key=lambda x: parse_date_any(x) or datetime.max)
    travel.sort(  key=lambda x: parse_date_any(x) or datetime.max)
    return schedule, dates, other, travel

def _strip_leading_time(text:str)->str:
    return TIME_LEADING_RE.sub("", text, count=1).strip()

# ----- GCAL Import (paged) ----------------------------------------------------
@app.post("/gcal/import_today_to_app")
@require_gcal
def gcal_import_today_to_app():
    import pytz
    email = session.get("email")
    if not email: return jsonify({"error": "not logged in"}), 401

    limit = max(1, min(int(request.args.get("limit", 60)), 500))
    page_token = request.args.get("pageToken")

    tz = pytz.timezone("Asia/Kolkata")
    start_local = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    end_local   = start_local + timedelta(days=1)

    svc = build_service()
    req = svc.events().list(
        calendarId="primary",
        singleEvents=True, orderBy="startTime",
        timeMin=start_local.astimezone(timezone.utc).isoformat(),
        timeMax=end_local.astimezone(timezone.utc).isoformat(),
        maxResults=min(limit, 200),
        pageToken=page_token,
        fields="items(start,summary,description),nextPageToken"
    )
    resp = req.execute()

    def _fmt_time(dt: datetime) -> str:
        hh = dt.hour % 12 or 12
        mm = f"{dt.minute:02d}"
        ap = "AM" if dt.hour < 12 else "PM"
        return f"{hh:02d}:{mm} {ap}"

    settings, lines = read_user_blob(email)
    existing = set(x.strip().lower() for x in lines if x.strip())
    out_lines = lines[:]
    added_time = added_date = 0
    consumed = 0

    for ev in resp.get("items", []):
        if consumed >= limit: break
        summary = (ev.get("summary") or "").strip()
        if not summary: continue
        if "created-by:scheduledsync" in (ev.get("description") or "").lower():
            continue
        start = ev.get("start", {})
        if "dateTime" in start:
            dt = datetime.fromisoformat(start["dateTime"].replace("Z", "+00:00")).astimezone(tz)
            line = summary if TIME_LEADING_RE.match(summary) else f"{_fmt_time(dt)} {summary}"
            key = line.lower()
            if key not in existing:
                out_lines.append(line); existing.add(key); added_time += 1
        elif "date" in start:
            d = datetime.fromisoformat(start["date"])
            line = f"{d.strftime('%b')} {int(d.strftime('%d'))} {summary}"
            key = line.lower()
            if key not in existing:
                out_lines.append(line); existing.add(key); added_date += 1
        else:
            continue
        consumed += 1

    if consumed:
        write_user_blob(email, settings, out_lines)

    return jsonify({
        "imported_time": added_time,
        "imported_dates": added_date,
        "total": added_time + added_date,
        "nextPageToken": resp.get("nextPageToken"),
        "limit": limit
    })

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

# ----- Dictionary-driven commands --------------------------------------------
def _export_all():
    ct = gcal_export_today().get_json(silent=True) or {}
    cd = gcal_export_dates().get_json(silent=True) or {}
    return {"today": ct, "dates": cd}

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

# ----- Probes / health --------------------------------------------------------
@app.get("/health")
def app_health(): return {"ok": True}

@app.get("/version")
def version(): return {"commit": os.getenv("RENDER_GIT_COMMIT", "local")}

@app.get("/time")
def time_now(): return {"server_time": datetime.now(timezone.utc).isoformat()}

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
    return render_template("index.html",
        email=email, schedule=schedule, dates=dates, other=other, travel=travel,
        travel_enabled=travel_enabled, now_ist=now_ist, session_has_gcal=bool(session.get("gcal"))
    )

@app.post("/toggle_travel")
def toggle_travel():
    email = session.get("email")
    if not email: flash("Login required."); return redirect(url_for("index"))
    settings, lines = read_user_blob(email)
    settings["travel_enabled"] = not settings.get("travel_enabled", False)
    write_user_blob(email, settings, lines)
    return redirect(url_for("index"))

@app.post("/add")
def add():
    email = session.get("email")
    if not email:
        flash("Login required."); return redirect(url_for("index"))
    text = request.form.get("add","").strip(); t = text.lower()
    if t in COMMANDS:
        resp = COMMANDS[t]()
        if isinstance(resp, dict):
            ct, cd = resp.get("today", {}), resp.get("dates", {})
            flash(f"Exported {int(ct.get('count',0))} time + {int(cd.get('count',0))} date events.")
        else:
            data = resp.get_json(silent=True) or {}
            if "total" in data: flash(f"Imported {int(data.get('total',0))} items from Google.")
            elif "count" in data: flash(f"Exported {int(data.get('count',0))} items to Google.")
        return redirect(url_for("index"))
    if text: append_line(email, text)
    return redirect(url_for("index"))

@app.post("/reset")
def reset():
    email = session.get("email")
    if not email: flash("Login required."); return redirect(url_for("index"))
    reset_user(email); flash("Data reset."); return redirect(url_for("index"))

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
def health_gcal(): return gcal_health_check()

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

@app.post("/gcal/export_today")
@require_gcal
def gcal_export_today():
    import pytz
    email = session.get("email")
    if not email: return jsonify({"error":"not logged in"}), 401
    limit = min(int(request.args.get("limit", 20)), 200)

    settings, lines = read_user_blob(email)
    schedule, _, _, _ = classify(lines)
    schedule = schedule[:limit]

    tz = pytz.timezone("Asia/Kolkata")
    today = tz.localize(datetime.now().replace(hour=0, minute=0, second=0, microsecond=0))
    svc = build_service()

    start_day_utc = today.astimezone(timezone.utc)
    end_day_utc   = (today + timedelta(days=1)).astimezone(timezone.utc)
    existing = set()
    existing_resp = svc.events().list(
        calendarId="primary", singleEvents=True, orderBy="startTime",
        timeMin=start_day_utc.isoformat(), timeMax=end_day_utc.isoformat(),
        maxResults=250
    ).execute()