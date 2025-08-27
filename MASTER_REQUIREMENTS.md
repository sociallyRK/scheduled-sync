# MASTER_REQUIREMENTS.md (LOCKED)

## Purpose
Single-page, minimal daily OS. Users add free-text lines; app classifies and displays them.

## Core Sections
1) Events (Schedule) — time-based lines  
2) Dates (Milestones) — `Mon DD …`  
3) Travel Schedule (optional) — `Mon DD` + location; shown under Settings when enabled  
4) Goals — line starts with `Goal:` or `To ` (case-insensitive)  
5) Other — everything else

## Classifier
- Events: time exists (start/anywhere) in `H[:MM] AM/PM`, or parseable by `dateutil`
- Dates: line starts with month short name + day (case-insensitive)
- Travel: a Date whose tail has city/country (`geotext`, `pycountry` with aliases US/USA/UK/UAE) or keyword `flight|fly|arrive|depart|airport|train|hotel|check-in|to`
- Goals: starts with `Goal:` or `To `; UI bolds “To”
- Sort: Events by time; Dates/Travel chronologically

## Storage
- Per-user file: `scheduled_data/<email>.txt`
- First line: `SETTINGS:{...}` JSON
- Start empty (no preload); new lines append

## Settings
- On the same page (no separate page)
- **One button**: toggle Travel Schedule
- Time format: 12-hour AM/PM only (display note)

## UI / Page
- Single HTML (`index.html`)
- **Three columns**:
  - Col 1: Events (Schedule) + add bar
  - Col 2: Dates + Other (Goals render with bold “To”)
  - Col 3: Login & Settings (one button; Travel list appears here when enabled)
- Add-bar placeholder (grey): `8 AM Breakfast, Dec 31 New Years Eve`

## Auth
- Email + password login/create on the page
- Logout clears session

## Endpoints
- GET `/`
- POST `/login`, `/logout`, `/add`, `/toggle_travel`, `/reset`
- GET `/healthz` → `ok`
- GET `/debug` → minimal diagnostics

## Run / Deploy
- Local: `python app.py` (port 5000)
- Render: `gunicorn app:app`
- Env: `APP_SECRET_KEY`
- Persistent disk for `scheduled_data/`
