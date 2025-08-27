cat <<'EOF' > MASTER_REQUIREMENTS.md
# MASTER_REQUIREMENTS.md

## Purpose
Single-page, minimal daily OS. Users add free-text lines; app classifies and displays them.

## Core Sections
1. **Events (Schedule)** — time-based lines  
   - If a line has both date + time → classify as **Event only** (no duplication in Dates).  
   - Sorted chronologically.  

2. **Dates (Milestones)** — `Mon DD …`  
   - Normalized display: `Mon DD Title Case`.  
   - Sorted chronologically.  

3. **Travel Schedule 🚆 (optional)** — `Mon DD` + location/keyword  
   - Detected via **GeoText**, **pycountry** (aliases: US, USA, UK, UAE), or keywords (`flight|fly|arrive|depart|airport|train|hotel|check-in|to`).  
   - When enabled, displayed **above Events**.  
   - Sorted chronologically.  

4. **Goals** — line starts with `Goal:` or `To ` (case-insensitive)  
   - Render with **To** bolded.  
   - Stored under “Other” internally.  

5. **Other** — everything else not classified above.  

---

## Classifier
- **Order:** Goal → Event (time anywhere) → Date (then Travel) → Other  
- **Events:** time exists (start/anywhere) in `H[:MM] AM/PM`, or parseable via `dateparser` (fallback: `dateutil`)  
- **Dates:** line starts with month short name + day (case-insensitive)  
- **Travel:** a Date whose tail has city/country (GeoText/pycountry) or keyword (`flight|fly|arrive|depart|airport|train|hotel|check-in|to`)  
- **Goals:** starts with `Goal:` or `To `; UI bolds “To”  
- **Sorting:** Events by time; Dates/Travel chronologically  

---

## Storage
- Per-user file: `scheduled_data/<email>.txt`  
- Filenames sanitized  
- First line: `SETTINGS:{...}` JSON  
- Start empty (no preload); new lines append  

### Settings JSON (schema)
```json
{
  "travel_enabled": false,
  "time_format": "12h",
  "use_llm": false
}
