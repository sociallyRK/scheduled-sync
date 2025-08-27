from flask import Flask, render_template, request, session, redirect
import os
from datetime import datetime
import pytz
import re

app = Flask(__name__)
app.secret_key = "your_secret_key"
DATA_DIR = "scheduled_data"

@app.route("/", methods=["GET", "POST"])
def index():
    if request.method == "POST":
        email = request.form.get("email")
        new_event = request.form.get("new_event")
        tz = request.form.get("timezone") or session.get("timezone")
        user = session.get("user") or email

        if email:
            session["user"] = email.lower()
            session["timezone"] = tz
            user_file = os.path.join(DATA_DIR, f"{email}.txt")
            if not os.path.exists(user_file):
                with open(user_file, "w") as f:
                    f.write("")
            return redirect("/")

        if new_event and user:
            user_file = os.path.join(DATA_DIR, f"{user}.txt")
            with open(user_file, "a") as f:
                f.write(f"{new_event.strip()}\n")
            return redirect("/")

    user = session.get("user")
    tz = session.get("timezone")

    if not user:
        return render_template("index.html", user=None)

    user_file = os.path.join(DATA_DIR, f"{user}.txt")

    schedule, milestones, development, other = [], [], [], []
    time_pattern = re.compile(r"^\d{1,2}:\d{2} ?[APap][Mm]")
    dev_keywords = ("Improve", "Raise", "Allocate")
    months = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
              "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")

    if os.path.exists(user_file):
        with open(user_file, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                if any(month in line for month in months):
                    milestones.append(line)
                elif line.startswith(dev_keywords):
                    development.append(line)
                elif time_pattern.match(line):
                    schedule.append(line)
                else:
                    other.append(line)

    schedule = [line.split(" ", 1) for line in schedule]
    tz_obj = pytz.timezone(tz) if tz else pytz.utc
    current_time = datetime.now(tz_obj).strftime("%A, %b %d — %I:%M %p")

    return render_template("index.html", user=user, current_time=current_time,
                           timezone=tz, schedule=schedule, milestones=milestones,
                           development=development, other=other)

@app.route("/reset")
def reset():
    user = session.get("user")
    if user:
        user_file = os.path.join(DATA_DIR, f"{user}.txt")
        with open(user_file, "w") as f:
            f.write("")
    return redirect("/")

if __name__ == "__main__":
    os.makedirs(DATA_DIR, exist_ok=True)
    app.run(debug=True)
EOF
