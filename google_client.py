import os, json, pathlib, datetime as dt, uuid
from flask import session
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
SCOPES = os.getenv("GOOGLE_SCOPES","https://www.googleapis.com/auth/calendar.events").split()
REDIRECT_URI = os.getenv("GOOGLE_REDIRECT_URI") or os.getenv("OAUTH_REDIRECT_URI")
DATA_DIR = pathlib.Path(os.getenv("PERSIST_DIR", "scheduled_data")); DATA_DIR.mkdir(parents=True, exist_ok=True)

def _safe_email() -> str:
    email = session.get("email") or "anon@example.com"
    return email.replace("@","_at_").replace(".","_")

def _token_path() -> pathlib.Path:
    return DATA_DIR / f"{_safe_email()}_gcal_token.json"

def _pending_path() -> pathlib.Path:
    return DATA_DIR / f"{_safe_email()}_gcal_pending.json"

def save_creds(creds: Credentials):
    _token_path().write_text(creds.to_json())

def load_creds() -> Credentials | None:
    p = _token_path()
    if not p.exists(): return None
    info = json.loads(p.read_text())
    creds = Credentials.from_authorized_user_info(info, SCOPES)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request()); save_creds(creds)
    return creds

def start_flow(state: str | None = None) -> Flow:
    flow = Flow.from_client_config(
        {"web":{"client_id":CLIENT_ID,"client_secret":CLIENT_SECRET,
                "auth_uri":"https://accounts.google.com/o/oauth2/auth",
                "token_uri":"https://oauth2.googleapis.com/token",
                "redirect_uris":[REDIRECT_URI]}},
        scopes=SCOPES)
    flow.redirect_uri = REDIRECT_URI
    if state: flow.state = state
    return flow

def build_service(creds: Credentials):
    return build("calendar","v3",credentials=creds,cache_discovery=False)

def ensure_authed():
    creds = load_creds()
    if not creds: return False, None
    try: return True, build_service(creds)
    except Exception: return False, None

def list_events_safe(max_results:int=10, calendar_id="primary"):
    ok, svc = ensure_authed()
    if not ok:
        return {"ok": False, "items": [], "message": "Google not connected. Reconnect and retry."}
    try:
        time_min = dt.datetime.utcnow().isoformat()+"Z"
        resp = svc.events().list(calendarId=calendar_id, timeMin=time_min,
                                 maxResults=max_results, singleEvents=True,
                                 orderBy="startTime").execute()
        return {"ok": True, "items": resp.get("items", [])}
    except Exception as e:
        return {"ok": False, "items": [], "message": "Calendar read failed. Try again later.", "error": str(e)}

def _queue(body:dict, calendar_id="primary"):
    p = _pending_path()
    q = json.loads(p.read_text()) if p.exists() else []
    q.append({"id": str(uuid.uuid4()), "calendar_id": calendar_id, "body": body, "queued_at": dt.datetime.utcnow().isoformat()+"Z"})
    p.write_text(json.dumps(q, indent=2))
    return q[-1]["id"]

def create_event_safe(summary:str, start_iso:str, end_iso:str, timezone:str="Asia/Kolkata", calendar_id="primary"):
    ok, svc = ensure_authed()
    body = {"summary": summary, "start":{"dateTime":start_iso,"timeZone":timezone}, "end":{"dateTime":end_iso,"timeZone":timezone}}
    if not ok:
        qid = _queue(body, calendar_id)
        return {"ok": False, "queued": True, "queued_id": qid, "message": "Not connected. Event queued."}
    try:
        ev = svc.events().insert(calendarId=calendar_id, body=body).execute()
        return {"ok": True, "event": ev}
    except Exception as e:
        qid = _queue(body, calendar_id)
        return {"ok": False, "queued": True, "queued_id": qid, "message": "Write failed. Event queued.", "error": str(e)}

def retry_pending():
    p = _pending_path()
    if not p.exists(): return {"attempted":0,"success":0,"failed":0,"remaining":0}
    ok, svc = ensure_authed()
    q = json.loads(p.read_text())
    if not ok: return {"attempted":0,"success":0,"failed":0,"remaining":len(q),"message":"Not connected"}
    new, s, f = [], 0, 0
    for item in q:
        try: svc.events().insert(calendarId=item["calendar_id"], body=item["body"]).execute(); s+=1
        except Exception: new.append(item); f+=1
    p.write_text(json.dumps(new, indent=2))
    return {"attempted":len(q),"success":s,"failed":f,"remaining":len(new)}
