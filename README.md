# Scheduled Web App (MVP)

A fast, minimal daily OS. Add entries in natural text; the app classifies and displays them on a single page.

---

## Core Sections
1. **Events** — time-based (`07:00 AM Yoga`, `tomorrow 2pm call mom`)
2. **Dates** — date-prefixed (`Aug 18 Finish presentation`)
3. **Travel 🚆** *(optional)* — date + location (`Aug 18 London`)
4. **Goals** — imperative (`Goal: Improve Collaboration`)
5. **Other** — everything else

---

## Input Rules
- **Events**: time format or phrase (via `dateparser`).
- **Dates**: `Mon DD`.
- **Travel**: date + city/country or travel keyword.
- **Goals**: starts with `Goal:` or `To `.
- **Other**: fallback.

---

## Settings
- **Show Travel Schedule** toggle.
- **12-hour AM/PM only**.
- Stored as first line JSON:  
  `SETTINGS:{"travel_enabled": false, "time_format": "12h"}`

---

## Data
- Per-user file: `scheduled_data/<email>.txt`

---

## 📌 Routes

| Route            | Method | Purpose |
|------------------|--------|---------|
| `/`              | GET    | Main page (events, dates, travel, other). |
| `/login`         | POST   | User login. |
| `/logout`        | POST   | User logout. |
| `/toggle_travel` | POST   | Toggle travel detection. |
| `/add`           | POST   | Add entry. |
| `/reset`         | POST   | Reset user data. |
| `/status`        | GET    | Service status. |
| `/healthz`       | GET    | Health check (Render). |
| `/debug`         | GET    | Debug info. |
| `/auth/gcal`     | GET    | Begin Google OAuth. |
| `/gcal/callback` | GET    | Google OAuth callback. |
| `/health/gcal`   | GET    | Check Google API. |
| `/gcal/next5`    | GET    | Show next 5 Google events. |
| `/gcal`          | GET    | Redirect to auth. |
| `/_envz`         | GET    | Masked env vars. |
| `/__routes`      | GET    | Show all routes. |

### ⚠️ Security
Disable `/debug`, `/_envz`, `/__routes` in production. Keep secrets (`APP_SECRET_KEY`, `GOOGLE_CLIENT_SECRET`) in Render Environment Settings.

---

## 🚀 Deploy on Render

### Procfile

### render.yaml
```yaml
services:
- type: web
  name: scheduled-staging
  runtime: python
  repo: https://github.com/sociallyRK/scheduled-sync
  buildCommand: pip install -r requirements.txt
  startCommand: gunicorn app:app --chdir . --bind 0.0.0.0:$PORT --timeout 120
  autoDeployTrigger: on
  plan: pro plus
