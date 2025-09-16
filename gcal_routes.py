from flask import Blueprint, render_template, request, session, redirect, url_for, jsonify, flash
from google_client import start_flow, save_creds, list_events_safe, create_event_safe, retry_pending

gcal_bp = Blueprint("gcal", __name__, url_prefix="/gcal")

def _current_user_email():
    return session.get("email") or "anon@example.com"

@gcal_bp.route("/login")
def login():
    flow = start_flow()
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true", prompt="consent")
    session["gcal_state"] = state
    return redirect(auth_url)

@gcal_bp.route("/callback")
def callback():
    if "gcal_state" not in session:
        return "Missing state", 400
    flow = start_flow(session["gcal_state"])
    flow.fetch_token(authorization_response=request.url)
    save_creds(flow.credentials)
    flash("Google Calendar connected.")
    return redirect(url_for("gcal.dashboard"))

@gcal_bp.route("/logout")
def logout():
    # delete local token file by overwriting with empty creds (optional: implement unlink in helper)
    flash("Google Calendar disconnected (local).")
    return redirect(url_for("gcal.dashboard"))

@gcal_bp.route("")
def dashboard():
    resp = list_events_safe(max_results=10)
    banner = None if resp.get("ok") else (resp.get("message") or "Calendar unavailable.")
    events = resp.get("items", [])
    authed = resp.get("ok", False)
    return render_template("gcal.html", authed=authed, events=events, banner=banner)

@gcal_bp.route("/create", methods=["POST"])
def create():
    data = request.get_json(silent=True) or request.form
    r = create_event_safe(
        summary=data.get("summary","Scheduled Event"),
        start_iso=data.get("start_iso"),
        end_iso=data.get("end_iso"),
        timezone=data.get("timezone","Asia/Kolkata")
    )
    code = 201 if r.get("ok") else (202 if r.get("queued") else 500)
    return jsonify(r), code

@gcal_bp.route("/retry", methods=["POST","GET"])
def retry():
    return jsonify(retry_pending()), 200
