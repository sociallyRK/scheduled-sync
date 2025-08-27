from flask import Flask, render_template, request, session, redirect
from datetime import datetime, timedelta
import os
import pytz
import re

app = Flask(__name__)
app.secret_key = "your_secret_key"
app.permanent_session_lifetime = timedelta(days=7)

DATA_DIR = "scheduled_data"
os.makedirs(DATA_DIR, exist_ok=True)

@app.before_request
def make_session_permanent():
    session.permanent = True

@app.route("/", methods=["GET", "POST"])
def index():
    user = session.get("user")
    tz = session.get("timezone", "Asia/Calcutta")

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        tz = request.form.get("timezone", "Asia/Calcutta")
        if email:
            session["user"] = email
            session["timezone"] = tz
        else:
            user = session.get("user")
            if user:
                file_path = os.path.join(DATA_DIR, f"{user}.txt")
                text = request.form.get("add", "").strip()
                if text:
                    with open(file_path, "a") as f:
                        f.write(text + "\n")

    user = session.get("user")
    events, dates, goals, others = [], [], [], []

    if user:
        file_path = os.path.join(DATA_DIR, f"{user}.txt")
        if os.path.exists(file_path):
            with open(file_path, "r") as f:
                lines = f.readlines()
            for line in lines:
                line = line.strip()
                if re.match(r"^\d{1,2}:\d{2} [APap][Mm]", line):
                    parts = line.split(" ", 2)
                    if len(parts) >= 2:
                        events.append((parts[0] + " " + parts[1], parts[2] if len(parts) == 3 else ""))
                elif re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\b", line):
                    dates.append(line)
                elif line.lower().startswith("dev:") or line.lower().startswith("goal:"):
                    goals.append(line)
                elif line:
                    others.append(line)

    now = datetime.now(pytz.timezone(tz)).strftime("%A, %b %d — %I:%M %p (%Z)")
    return render_template("index.html", user=user, events=events, dates=dates, goals=goals, others=others, now=now)

@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    return redirect("/")

# Works on both Replit and Render
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
