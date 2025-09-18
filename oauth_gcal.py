"""
Google Calendar OAuth helpers (Flow + session + client).
Drop this beside app.py.
"""
import os, uuid, time, json
from functools import wraps
from flask import current_app, session, request, url_for, redirect, jsonify
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from google_auth_oauthlib.flow import Flow
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

AUTH_URI = "https://accounts.google.com/o/oauth2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"

def _ser():
    secret = os.getenv("APP_SECRET_KEY") or current_app.config.get("SECRET_KEY")
    return URLSafeTimedSerializer(secret, salt="gcal-oauth")

def _redirect_uri():
    path = os.getenv("GCAL_REDIRECT_PATH", "/gcal/callback")
    return url_for("gcal_callback", _external=True, _scheme="https") if path == "/gcal/callback" \
        else request.url_root.rstrip("/") + path

def _client_config():
    rid = _redirect_uri()
    cid = os.getenv("GOOGLE_CLIENT_ID")
    csec = os.getenv("GOOGLE_CLIENT_SECRET")
    if not all([cid, csec]):
        raise RuntimeError("Missing GOOGLE_CLIENT_ID/GOOGLE_CLIENT_SECRET")
    return {
        "web": {
            "client_id": cid,
            "client_secret": csec,
            "redirect_uris": [rid],
            "auth_uri": AUTH_URI,
            "token_uri": TOKEN_URI
        }
    }

def _scopes():
    raw = os.getenv("GOOGLE_SCOPES", "https://www.googleapis.com/auth/calendar.readonly")
    return [s.strip() for s in raw.split(",") if s.strip()]

def begin_auth(next_url="/"):
    payload = {"nonce": uuid.uuid4().hex, "t": int(time.time()), "next": next_url}
    state = _ser().dumps(payload)
    flow = Flow.from_client_config(_client_config(), scopes=_scopes(), redirect_uri=_redirect_uri())
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        prompt="consent",
        state=state,
    )
    return auth_url

def finish_auth(authorization_response: str, max_age=600):
    state = request.args.get("state")
    if not state:
        raise RuntimeError("Missing OAuth state")
    try:
        payload = _ser().loads(state, max_age=max_age)
    except SignatureExpired:
        raise RuntimeError("Expired OAuth state")
    except BadSignature:
        raise RuntimeError("Bad OAuth state")

    flow = Flow.from_client_config(_client_config(), scopes=_scopes(), redirect_uri=_redirect_uri())
    flow.fetch_token(authorization_response=authorization_response)
    creds = flow.credentials
    info = json.loads(creds.to_json())
    session["gcal"] = info
    return payload.get("next") or "/"

def build_service():
    info = session.get("gcal")
    if not info:
        raise RuntimeError("No Google credentials in session")
    creds = Credentials.from_authorized_user_info(info)
    return build("calendar", "v3", credentials=creds, cache_discovery=False)

def require_gcal(fn):
    @wraps(fn)
    def wrap(*a, **k):
        if not session.get("gcal"):
            return redirect(begin_auth(request.full_path or "/"))
        return fn(*a, **k)
    return wrap

def health():
    ok = {
        "redirect_uri": _redirect_uri(),
        "have_client_id": bool(os.getenv("GOOGLE_CLIENT_ID")),
        "have_client_secret": bool(os.getenv("GOOGLE_CLIENT_SECRET")),
        "scopes": _scopes(),
        "session_has_gcal": bool(session.get("gcal")),
        "url_root": request.url_root,
        "now": int(time.time()),
    }
    return jsonify(ok)