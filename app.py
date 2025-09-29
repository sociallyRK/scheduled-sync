import os, json, re, datetime as dt
from datetime import timezone
from flask import Flask, redirect, request, session, url_for, render_template, jsonify
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build

# ===== Config =====
APP_SECRET = os.environ.get("SECRET_KEY", "dev-secret")
GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
GOOGLE_CLIENT_SECRET = os.environ["GOOGLE_CLIENT_SECRET"]
GOOGLE_REDIRECT_URI = os.environ.get("GOOGLE_REDIRECT_URI", "https://your.app/oauth2callback")
SCOPES = ["https://www.googleapis.com/auth/calendar.readonly"]

app = Flask(__name__)
app.secret_key = APP_SECRET

# ===== OAuth Helpers =====
def _flow():
    return Flow(
        client_config={
            "web": {
                "client_id": GOOGLE_CLIENT_ID,
                "project_id": "scheduled",
                "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                "token_uri": "https://oauth2.googleapis.com/token",
                "client_secret": GOOGLE_CLIENT_SECRET,
                "redirect_uris": [GOOGLE_REDIRECT_URI],
                "javascript_origins": []
            }
        },
        scopes=SCOPES,
        redirect_uri=GOOGLE_REDIRECT_URI,
    )

def _get_creds():
    tok = session.get("token")
    if not tok: return None
    creds = Credentials.from_authorized_user_info(tok, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
            session["token"] = json.loads(creds.to_json())
        except Exception:
            session.pop("token", None)
            return None
    return creds

# ===== Utility =====
def now_utc_iso(): return dt.datetime.now(timezone.utc).isoformat()
def in_days_iso(days): return (dt.datetime.now(timezone.utc)+dt.timedelta(days=days)).isoformat()

# Simple regexes to pull travel data
AIRLINE_HINTS = r"(UA|United|AA|American|DL|Delta|BA|British|LH|Lufthansa|AI|Air India|Vistara|IndiGo)"
CITY_RX = r"(New York|Los Angeles|San Francisco|Mumbai|Delhi|Bengaluru|Chicago|Miami|London|Paris|Dubai)"

def parse_trips(events):
    trips = []
    for ev in events:
        title = (ev.get("summary") or "") + " " + (ev.get("location") or "")
        if re.search(AIRLINE_HINTS, title, re.I) or "Flight" in title:
            trips.append({
                "type": "flight",
                "title": ev.get("summary"),
                "start": ev.get("start"),
                "end": ev.get("end"),
                "city": _first_or_none(re.findall(CITY_RX, title, re.I)),
            })
        elif "Hotel" in title:
            trips.append({
                "type": "hotel",
                "title": ev.get("summary"),
                "start": ev.get("start"),
                "end": ev.get("end"),
                "city": _first_or_none(re.findall(CITY_RX, title, re.I)),
            })
    return trips

def _first_or_none(seq): return seq[0] if seq else None

# ===== Routes =====
@app.route("/")
def home():
    creds = _get_creds()
    if not creds:
        return render_template("index.html", signed_in=False, events=[], error=None)
    try:
        service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        resp = service.events().list(
            calendarId="primary",
            singleEvents=True,
            orderBy="startTime",
            timeMin=now_utc_iso(),
            timeMax=in_days_iso(14),
            maxResults=50
        ).execute()
        items = []
        for ev in resp.get("items", []):
            s = ev.get("start", {}); e = ev.get("end", {})
            items.append({
                "summary": ev.get("summary", "(No title)"),
                "location": ev.get("location"),
                "start": s.get("dateTime") or (s.get("date")+"T00:00:00" if s.get("date") else None),
                "end": e.get("dateTime") or (e.get("date")+"T00:00:00" if e.get("date") else None),
                "status": ev.get("status"),
                "htmlLink": ev.get("htmlLink"),
            })
        session["last_events"] = items
        session["last_trips"] = parse_trips(items)
        return render_template("index.html", signed_in=True, events=items, error=None)
    except Exception as ex:
        session["last_error"] = str(ex)
        return render_template("index.html", signed_in=True, events=[], error="Couldn’t load Google Calendar."), 500

@app.route("/api/events")
def api_events():
    try:
        return jsonify({"ok": True, "items": session.get("last_events", [])})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500

@app.route("/api/travel")
def api_travel():
    try:
        return jsonify({"ok": True, "trips": session.get("last_trips", [])})
    except Exception as ex:
        return jsonify({"ok": False, "error": str(ex)}), 500

@app.route("/login")
def login():
    flow = _flow()
    auth_url, state = flow.authorization_url(include_granted_scopes="true", access_type="offline", prompt="consent")
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    flow = _flow()
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["token"] = json.loads(creds.to_json())
    return redirect(url_for("home"))

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("home"))

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)