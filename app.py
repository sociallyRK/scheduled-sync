# top of app.py
try:
    # Preferred: dateparser (handles "tomorrow 2pm", etc.)
    from dateparser import parse as _parse_date
except Exception:
    # Fallback: python-dateutil
    from dateutil import parser as _du_parser
    _parse_date = _du_parser.parse

import os, re, json
from pathlib import Path
from datetime import datetime
from flask import Flask, request, render_template, redirect, session, url_for, flash
from geotext import GeoText
import pycountry


BASE = Path(__file__).parent.resolve()
DATA_DIR = BASE / "scheduled_data"; DATA_DIR.mkdir(exist_ok=True)
USERS = BASE / "users.json"

app = Flask(__name__, template_folder=str(BASE), static_folder=str(BASE))
app.secret_key = os.environ.get("APP_SECRET_KEY", "dev_secret_change_me")

# --- Regex helpers ------------------------------------------------------------
MONTHS = "Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split()
DATE_PREFIX_RE = re.compile(r"^\s*(?:(" + "|".join(MONTHS) + r")\.?)\s+(\d{1,2})\b", re.I)
TIME_ANY_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)  # anywhere
TIME_START_RE = re.compile(r"^\s*(\d{1,2})(?::(\d{2}))?\s*(AM|PM)\b", re.I)
GOAL_RE = re.compile(r"^\s*(Goal:|To\s)\b", re.I)
TRAVEL_KEYWORDS = re.compile(r"\b(flight|fly|arrive|depart|airport|train|hotel|check-?in|to)\b", re.I)

# --- File helpers (settings INSIDE user's .txt) -------------------------------
def _safe(email:str)->str: return re.sub(r"[^a-z0-9_.@+-]+","_",email.lower())
def user_file(email:str)->Path: return DATA_DIR / f"{_safe(email)}.txt"

def _default_settings(): return {"travel_enabled": False, "time_format": "12h"}

def load_users():
    return json.loads(USERS.read_text()) if USERS.exists() else {}

def save_users(d):
    USERS.write_text(json.dumps(d, indent=2))

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
    settings, lines = read_user_blob(email)
    lines.append(text.strip())
    write_user_blob(email, settings, lines)

def reset_user(email:str):
    write_user_blob(email, _default_settings(), [])

# --- Parse helpers ------------------------------------------------------------
def parse_time_tuple(line:str):
    m = TIME_START_RE.match(line)
    if not m: m = TIME_ANY_RE.search(line)
    if not m: return None
    h = int(m.group(1)); minute = int(m.group(2) or 0); ampm = m.group(3).upper()
    h = 0 if h == 12 else h
    if ampm == "PM": h += 12
    return (h, minute)

def parse_date_prefix(line:str):
    m = DATE_PREFIX_RE.match(line)
    if not m: return None
    mon, day = m.group(1), int(m.group(2))
    try:
        return _parse_date(f"{mon} {day} {datetime.now().year}")
    except Exception:
        return None

def is_goal(line:str) -> bool:
    return bool(GOAL_RE.match(line))

def _pycountry_match(word:str) -> bool:
    w = word.upper().strip(".,;:!?")
    alias = {"US":"UNITED STATES", "USA":"UNITED STATES", "UAE":"UNITED ARAB EMIRATES", "UK":"UNITED KINGDOM"}
    if w in alias: w = alias[w]
    try:
        return pycountry.countries.lookup(w) is not None
    except LookupError:
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
        if is_goal(ln):
            other.append(ln)  # Goals live under Dates+Other per layout
        elif parse_time_tuple(ln):
            schedule.append(ln)
        elif parse_date_prefix(ln):
            (travel if is_travel(ln) else dates).append(ln)
        else:
            other.append(ln)
    schedule.sort(key=lambda x: parse_time_tuple(x) or (99, 99))
    dates.sort(key=lambda x: parse_date_prefix(x) or datetime.max)
    travel.sort(key=lambda x: parse_date_prefix(x) or datetime.max)
    return schedule, dates, other, travel

# --- Auth ---------------------------------------------------------------------
@app.post("/login")
def login():
    email = request.form.get("email","").strip().lower()
    password = request.form.get("password","").strip()
    if not email or not password:
        flash("Email and password required."); return redirect(url_for("index"))
    users = load_users()
    if email in users:
        if users[email].get("password") != password:
            flash("Incorrect password."); return redirect(url_for("index"))
    else:
        users[email] = {"password": password}
        save_users(users)
    session["email"] = email
    flash("Logged in.")
    return redirect(url_for("index"))

@app.post("/logout")
def logout():
    session.clear(); flash("Logged out."); return redirect(url_for("index"))

# --- Single-button Settings ---------------------------------------------------
@app.post("/toggle_travel")
def toggle_travel():
    email = session.get("email")
    if not email: flash("Login required."); return redirect(url_for("index"))
    settings, lines = read_user_blob(email)
    settings["travel_enabled"] = not settings.get("travel_enabled", False)
    write_user_blob(email, settings, lines)
    return redirect(url_for("index"))

# --- Actions ------------------------------------------------------------------
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

# --- Diagnostics --------------------------------------------------------------
@app.get("/healthz")
def healthz(): return "ok", 200

@app.get("/debug")
def debug():
    return {
        "email": session.get("email"),
        "files": [p.name for p in DATA_DIR.glob("*.txt")],
        "users_file": USERS.exists(),
    }

# --- Main ---------------------------------------------------------------------
@app.get("/")
def index():
    email = session.get("email")
    schedule = dates = other = travel = []
    travel_enabled = False
    if email:
        settings, lines = read_user_blob(email)
        travel_enabled = settings.get("travel_enabled", False)
        schedule, dates, other, travel = classify(lines)
    return render_template("index.html",
        email=email, schedule=schedule, dates=dates, other=other,
        travel=travel, travel_enabled=travel_enabled)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)

from gcal_routes import gcal_bp
app.register_blueprint(gcal_bp)
from flask import redirect, url_for
@app.route("/auth/google")
def auth_google_alias():
    return redirect(url_for("gcal.login"))

@app.route("/auth/google/callback")
def auth_google_callback_alias():
    return redirect(url_for("gcal.callback"))
