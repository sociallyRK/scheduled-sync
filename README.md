# Scheduled Web App (MVP)

A fast, minimal daily OS. Add entries in natural text; the app classifies and displays them on a single page.

---

## Core Sections
1. **Events** — time-based (e.g., `07:00 AM Yoga`, `tomorrow 2pm call mom`)
2. **Dates (Milestones)** — date-prefixed (e.g., `Aug 18 Finish presentation`)
3. **Travel Schedule 🚆** *(optional)* — **date + location** (e.g., `Aug 18 London`, `Sept 21 to Shirdi`)
4. **Goals** — imperative statements (e.g., `Goal: Improve Collaboration`, `To Eat Healthier`)
5. **Other** — everything else

---

## Input Rules (Classifier)
- **Events**: starts with `H:MM/HH:MM AM/PM`, **or** contains a recognizable time phrase (via `dateparser`).
- **Dates**: starts with `Mon DD` (month short name).
- **Travel**: a **Date** line that also contains a detected **city/country** (`geotext`/`pycountry`) or travel keyword (`flight|train|airport|hotel|to`, etc.).
- **Goals**: starts with `Goal:` or `To ` (case-insensitive).
- **Other**: fallback.

---

## Settings (in main page)
- **Show Travel Schedule** toggle.
- **12-hour AM/PM only**.
- Persisted in per-user file as lines like: `::setting:show_travel=1`.

---

## Data
- Per-user file: `scheduled_data/<email>.txt`
- If file exists → load & append. If not → start empty. No preloads.

---

## Routes
- `/` main (login + dashboard)
- `/add` append a single natural-text line
- `/logout` clear session
- `/reset` delete user data file
- `/status` simple HTML service status (no extra template)
- `/healthz` JSON health check

---

## Local Run
```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
gunicorn app:app --bind 0.0.0.0:5000
# visit http://127.0.0.1:5000


---

## Local development

    make run

Creates a venv (if missing), installs deps, and runs Flask in debug.

## Production-like run

    make gunicorn

Runs Gunicorn on 0.0.0.0:5000.

## Lint & format

    make lint      # ruff
    make format    # black

First call installs dev tools in the venv.

## Deploy

    make deploy

Pushes main to GitHub (Render will auto-deploy if connected).

## Env
See \`.env.example\`. Copy to \`.env\` and adjust later if you add python-dotenv.
