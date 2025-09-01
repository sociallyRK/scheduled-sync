# app.py — dual callbacks + PKCE + two-way Google sync + first-callback-wins state
try:
    from dateparser import parse as _parse_date
except Exception:
    from dateutil import parser as _du_parser
    _parse_date = _du_parser.parse

import os, re, json
from pathlib import Path
from datetime import datetime, timedelta
from flask import Flask, request, render_template, redirect, session, url_for, flash
from geotext import GeoText
from dotenv import load_dotenv
load_dotenv()

# --- Google OAuth / API -------------------------------------------------------
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

# WRITE scope for two-way sync
GOOGLE_SCOPES = ["https://www.googleapis.com/auth/calendar"]

# Allow HTTP locally in dev
if os.environ.get("FLASK_ENV") == "development":
    os.environ.setdefault("OAUTHLIB_INSECURE_TRANSPORT", "1")

BASE = Path(__file__).parent.resolve()
DATA_DIR = BASE / "scheduled_data"; DATA_DIR.mkdir(exist_ok=True)
USERS = BASE / "users.json"

app = Flask(__name__, template_folder=str(BASE), static_folder=str(BASE))
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev_secret_change_me")

# =========================
# Parsing / classification
# =========================
MONTH_PAT = r"(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep(?:t)?|Oct|Nov|Dec)"
DATE_PREFIX_RE = re.compile(rf"^\s*(?:{MONTH_PAT}\.?)\s+(\d{{1,2}})\b", re.I)

TIME_ANY_RE   = re.compile(r"\b(\d{1,2})(?::(\d{1,2}))?\s*(AM|PM)\b", re.I)
TIME_START_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{1,2}))?\s*(AM|PM)\b", re.I)

GOAL_RE = re.compile(r"^\s*(Goal:|To\s)\b", re.I)
TRAVEL_KEYWORDS = re.compile(r"\b(flight|fly|arrive|depart|airport|train|hotel|check-?in|to)\b", re.I)

MONTHS_THREE = {"Jan","Feb","Mar","Apr","May","Jun","Jul","Aug","Sep","Oct","Nov","Dec"}

def _normalize_month_token(tok:str)->str:
    t = tok.strip(". ").lower()
    if t.startswith("sept"): return "Sep"
    return (tok[:3].title() if tok[:3].title() in MONTHS_THREE else tok.title())

def parse_time_tuple(line:str):
    m = TIME_START_RE.match(line) or TIME_ANY_RE.search(line)
    if not m: return None
    h = int(m.group(1)); minute = int(m.group(2) or 0); ampm = m.group(3).upper()
    h = 0 if h == 12 else h
    if ampm == "PM": h += 12
    return (h, minute)

def format_time_in_line(line:str) -> str:
    m = TIME_ANY_RE.search(line)
    if not m: return line
    h = int(m.group(1)); minute = int(m.group(2) or 0); ampm = m.group(3).upper()
    h12 = 12 if h % 12 == 0 else h % 12
    token = f"{h12:02d}:{minute:02d} {ampm}"
    start, end = m.span()
    return line[:start] + token + line[end:]

def parse_date_prefix(line:str):
    m = DATE_PREFIX_RE.match(line)
    if not m: return None
    mon_raw, day = m.group(1), int(m.group(2))
    mon = _normalize_month_token(mon_raw)
    try:
        return _parse_date(f"{mon} {day} {datetime.now().year}")
    except Exception:
        return None

def is_goal(line:str) -> bool:
    return bool(GOAL_RE.match(line))

def _pycountry_match(word:str) -> bool:
    try:
        import pycountry
        w = word.upper().strip(".,;:!?")
        alias = {"US":"UNITED STATES","USA":"UNITED STATES","UAE":"UNITED ARAB EMIRATES","UK":"UNITED KINGDOM"}
        if w in alias: w = alias[w]
        return pycountry.countries.lookup(w) is not None
    except Exception:
        return False

def is_travel(line:str) -> bool:
    if not parse_date_prefix(line): return False
    tail = DATE_PREFIX_RE.sub("", line).strip()
    geo = GeoText(tail)
    has_city_country = bool(geo.cities or geo.countries) or any(_pycountry_match(tok) for tok in tail.split())
    has_keyword = bool(TRAVEL_KEYWORDS.search(tail))
    return has_city_country or has_keyword

def classify(lines:list[str]):
    schedule, dates, other, travel = [], [], [], []
    for ln in lines:
        if is_goal(ln): other.append(ln)
        elif parse_time_tuple(ln): schedule.append(ln)
        elif parse_date_prefix(ln): (travel if is_travel(ln) else dates).append(ln)
        else: other.append(ln)
    schedule.sort(key=lambda x: parse_time_tuple(x) or (99,99))
    dates.sort(key=lambda x: parse_date_prefix(x) or datetime.max)
    travel.sort(key=lambda x: parse_date_prefix(x) or datetime.max)
    schedule = [format_time_in_line(ln) for ln in schedule]
    month_fix = lambda s: re.sub(MONTH_PAT, lambda mo: _normalize_month_token(mo.group(0)), s, count=1, flags=re.I)
    dates  = [month_fix(ln) for ln in dates]
    travel = [month_fix(ln) for ln in travel]
    return schedule, dates, other, travel

# =========================
# Storage helpers
# =========================
def _safe(email:str)->str: return re.sub(r"[^a-z0-9_.@+-]+","_",email.lower())
def user_file(email:str)->Path: return DATA_DIR / f"{_safe(email)}.txt"
def _default_settings(): return {"travel_enabled": False, "time_format": "12h"}

def load_users(): return json.loads(USERS.read_text()) if USERS.exists() else {}
def save_users(d): USERS.write_text(json.dumps(d, indent=2))

def read_user_blob(email:str):
    p = user_file(email)
    if not p.exists(): p.write_text(f"SETTINGS:{json.dumps(_default_settings())}\n", encoding="utf-8")
    raw = p.read_text(encoding="utf-8").splitlines()
    if raw and raw[0].startswith("SETTINGS:"):
        try: settings = json.loads(raw[0][9:])
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
    settings, lines = read_user_blob(email)
    lines.append(text.strip()); write_user_blob(email, settings, lines)

def reset_user(email:str): write_user_blob(email, _default_settings(), [])

# =========================
# Local auth
# =========================
@app.post("/login")
def login():
    email = request.form.get("email","").strip().lower()
    password = request.form.get("password","").strip()
    if not email or not password:
        flash("Email and password required."); return redirect(url_for("index"))
    users = load_users()
    if email in users and users[email].get("password") != password:
        flash("Incorrect password."); return redirect(url_for("index"))
    users[email] = {"password": password}; save_users(users)
    session["email"] = email; flash("Logged in.")
    return redirect(url_for("index"))

@app.post("/logout")
def logout():
    session.clear(); flash("Logged out."); return redirect(url_for("index"))

# =========================
# Settings & actions
# =========================
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
    if not email: flash("Login required."); return redirect(url_for("index"))
    text = request.form.get("add","").strip()
    if text: append_line(email, text)
    return redirect(url_for("index"))

@app.post("/reset")
def reset():
    email = session.get("email")
    if not email: flash("Login required."); return redirect(url_for("index"))
    reset_user(email); flash("Data reset."); return redirect(url_for("index"))

# =========================
# Diagnostics
# =========================
@app.get("/healthz")
def healthz(): return "ok", 200

@app.get("/debug")
def debug():
    return {
        "email": session.get("email"),
        "g_scopes": session.get("g_creds", {}).get("scopes"),
        "files": [p.name for p in DATA_DIR.glob("*.txt")],
        "users_file": USERS.exists(),
    }

# =========================
# Google OAuth (dual callbacks, PKCE, idempotent state)
# =========================
def _get_google_cfg():
    raw = os.environ.get("GOOGLE_OAUTH_CLIENT_JSON")
    if raw: return json.loads(raw)
    cid = os.environ.get("GOOGLE_CLIENT_ID"); csec = os.environ.get("GOOGLE_CLIENT_SECRET")
    if not (cid and csec): raise RuntimeError("Missing GOOGLE_OAUTH_CLIENT_JSON or GOOGLE_CLIENT_ID/SECRET")
    return {"web":{"client_id":cid,"client_secret":csec,
                   "auth_uri":"https://accounts.google.com/o/oauth2/auth",
                   "token_uri":"https://oauth2.googleapis.com/token"}}

def _states(): return set(session.get("g_states", []))
def _save_states(s): session["g_states"] = list(s)

@app.get("/auth/google")
def auth_google():
    cfg = _get_google_cfg()
    redirect_uri = url_for("oauth2callback", _external=True)  # canonical
    flow = Flow.from_client_config(cfg, scopes=GOOGLE_SCOPES, redirect_uri=redirect_uri)
    auth_url, state = flow.authorization_url(
        access_type="offline", include_granted_scopes="true",
        prompt="consent", code_challenge_method="S256"
    )
    s = _states(); s.add(state); _save_states(s)
    return redirect(auth_url)

@app.get("/oauth2callback")
@app.get("/oauth2/callback")
def oauth2callback():
    incoming_state = request.args.get("state")
    s = _states()
    if incoming_state not in s:
        flash("Invalid or already-used state."); return redirect(url_for("index"))
    s.remove(incoming_state); _save_states(s)

    cfg = _get_google_cfg()
    flow = Flow.from_client_config(cfg, scopes=GOOGLE_SCOPES,
                                   state=incoming_state, redirect_uri=request.base_url)
    flow.fetch_token(authorization_response=request.url)
    c = flow.credentials
    session["g_creds"] = {
        "token": c.token, "refresh_token": getattr(c,"refresh_token",None),
        "token_uri": c.token_uri, "client_id": c.client_id,
        "client_secret": c.client_secret, "scopes": c.scopes,
    }
    flash("Google connected.")
    return redirect(url_for("index"))

def _gservice():
    g = session.get("g_creds")
    if not g: return None
    creds = Credentials(token=g["token"],
                        refresh_token=g.get("refresh_token"),
                        token_uri=g["token_uri"],
                        client_id=g["client_id"],
                        client_secret=g["client_secret"],
                        scopes=g.get("scopes", GOOGLE_SCOPES))
    return build("calendar","v3",credentials=creds, cache_discovery=False)

# =========================
# Google ←→ Local sync
# =========================
def _today_range_ist():
    # Use DISPLAY_TZ if provided, else IST
    from dateutil import tz as _tz
    zone = _tz.gettz(os.environ.get("DISPLAY_TZ", "Asia/Kolkata"))
    start = datetime.now(zone).replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    return start, end

@app.post("/import_google")
def import_google():
    email = session.get("email"); service = _gservice()
    if not (email and service):
        flash("Login + Google connect required."); return redirect(url_for("index"))
    start, end = _today_range_ist()
    timeMin = start.astimezone().isoformat()
    timeMax = end.astimezone().isoformat()
    res = service.events().list(calendarId="primary", timeMin=timeMin, timeMax=timeMax,
                                singleEvents=True, orderBy="startTime", maxResults=100).execute()
    settings, lines = read_user_blob(email)
    for ev in res.get("items", []):
        s = ev.get("start", {})
        title = ev.get("summary") or "(No title)"
        if "date" in s:
            # all-day -> Dates
            dt = datetime.fromisoformat(s["date"])
            line = f"{dt.strftime('%b')} {dt.day} {title}"
        else:
            dt = datetime.fromisoformat(ev["start"]["dateTime"].replace("Z","+00:00")).astimezone()
            line = f"{dt.strftime('%I:%M %p')} {title}"
        if line not in lines: lines.append(line)
    write_user_blob(email, settings, lines)
    flash("Imported today’s Google events.")
    return redirect(url_for("index"))

@app.post("/export_google")
def export_google():
    email = session.get("email"); service = _gservice()
    if not (email and service):
        flash("Login + Google connect required."); return redirect(url_for("index"))
    settings, lines = read_user_blob(email)
    schedule, _, _, _ = classify(lines)

    # Build today's existing events map to avoid dups: (summary, HH:MM)
    start, end = _today_range_ist()
    timeMin = start.astimezone().isoformat(); timeMax = end.astimezone().isoformat()
    existing = {}
    res = service.events().list(calendarId="primary", timeMin=timeMin, timeMax=timeMax,
                                singleEvents=True, orderBy="startTime", maxResults=250).execute()
    for ev in res.get("items", []):
        if "dateTime" in ev.get("start", {}):
            dt = datetime.fromisoformat(ev["start"]["dateTime"].replace("Z","+00:00")).astimezone()
            key = ((ev.get("summary") or "").strip(), dt.strftime("%H:%M"))
            existing[key] = True

    created = 0
    for ln in schedule:
        m = TIME_START_RE.match(ln)
        if not m: continue
        hour = int(m.group(1)); minute = int(m.group(2) or 0); ampm = m.group(3).upper()
        hour = (0 if hour==12 else hour) + (12 if ampm=="PM" else 0)
        title = ln[m.end():].strip() or "Scheduled Event"
        start_dt = start.replace(hour=hour, minute=minute)
        end_dt = start_dt + timedelta(minutes=60)
        key = (title, start_dt.strftime("%H:%M"))
        if key in existing: continue
        body = {
            "summary": title,
            "start": {"dateTime": start_dt.astimezone().isoformat()},
            "end":   {"dateTime": end_dt.astimezone().isoformat()},
        }
        service.events().insert(calendarId="primary", body=body).execute()
        created += 1

    flash(f"Exported {created} event(s) to Google.")
    return redirect(url_for("index"))

@app.get("/logout_google")
def logout_google():
    session.pop("g_creds", None)
    flash("Disconnected Google.")
    return redirect(url_for("index"))

# =========================
# Main UI
# =========================
@app.get("/")
def index():
    email = session.get("email")
    schedule = dates = other = travel = []
    travel_enabled = False
    if email:
        settings, lines = read_user_blob(email)
        travel_enabled = settings.get("travel_enabled", False)
        schedule, dates, other, travel = classify(lines)
    now_ist = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return render_template("index.html",
        email=email, schedule=schedule, dates=dates, other=other,
        travel=travel, travel_enabled=travel_enabled, now_ist=now_ist)

# =========================
# Entrypoint
# =========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
