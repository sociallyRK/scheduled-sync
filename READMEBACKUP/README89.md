# Scheduled Web App (MVP)

A fast, minimal daily OS that allows users to add entries in natural text. The app classifies and displays them on a single page.

---

## Core Sections

1. **Events** — Time-based events (e.g., `07:00 AM Yoga`, `tomorrow 2pm call mom`)
2. **Dates (Milestones)** — Date-prefixed (e.g., `Aug 18 Finish presentation`)
3. **Travel Schedule 🚆** *(optional)* — **Date + Location** (e.g., `Aug 18 London`, `Aug 20 Flight to India`, `Sept 21 to Shirdi`)
4. **Goals** — Imperative statements (e.g., `Goal: Improve Collaboration`, `To Eat Healthier`)
5. **Other** — Everything else (non-categorized events or notes)

---

## Input Rules (Classifier)

The app uses a **natural language classifier** to categorize user input into one of the core sections above. The rules for classification are as follows:

### **Events**
- **Format**:  
   - Line starts with a time, either in `H:MM/HH:MM AM/PM` format, **OR**  
   - Natural language includes a time (parsed via `dateparser`).

   **Examples**:
   - `09:30 AM Code` → Event
   - `tomorrow 2pm call mom` → Event

### **Goals**
- **Format**:  
   - Line starts with `Goal:` **or** starts with `To ` (case-insensitive). **UI bolds** `To`.

   **Examples**:
   - `Goal: Improve Collaboration` → Goal
   - `To Eat Healthier` → Goal

### **Dates/Travel**
- **Format**:  
   - Line starts with `Mon DD` (month short name, case-insensitive).  
   - If the **line starts with a date prefix** and the **tail contains a location**, it’s classified as **Travel**.  
   - Otherwise, it’s classified as a **Date**.

   **Examples**:
   - `Aug 18 London` → Travel 🚆
   - `Aug 20 Flight to India` → Travel 🚆
   - `Sept 21 to Shirdi` → Travel 🚆
   - `Aug 19 Finish presentation` → Date

---

## Travel Location Detection

**Travel entries** are detected using a combination of location-related keywords and location names.

1. **`geotext`** finds **cities** or **countries**.
2. **`pycountry`** matches countries (aliases: `UK`, `UAE`, `USA`, `US`).
3. **Travel keyword + Proper-Noun span**:  
   Travel-related keywords include `flight|fly|arrive|depart|airport|train|hotel|check-in|to`, followed by `Capitalized Word(s)`.

   **Examples**:
   - `Aug 18 London` → Travel 🚆
   - `Aug 20 Flight to India` → Travel 🚆
   - `Sept 21 to Shirdi` → Travel 🚆
   - `09:30 AM Code` → Event
   - `tomorrow 2pm call mom` → Event

---

## Settings (Embedded in `index.html`)

The app allows users to adjust settings related to the display and format of events. Settings are available directly on the main page, with a toggle for showing the **Travel Schedule** and a choice for the **time format**.

### Available Settings:

- **Show Travel Schedule** (on/off)
- **Time Format** — **12-hour AM/PM only** (no 24-hour toggle)

**Settings** are **hidden by default** and can be revealed via a **“Settings”** link. There is **no separate settings page**—everything is integrated into the main page.

---

## Settings Storage

Settings are stored in the user’s data file located at `scheduled_data/<email>.txt`. This ensures that settings persist between sessions and are dynamically updated as the user makes changes.

---

## Data File Handling

### **File Structure**:
- When a user logs in, the app checks for the existence of a file for that user at `scheduled_data/<email>.txt`.
  
### **File Behavior**:
- If the file **already exists**:
  - The app **loads and displays** the existing data.
  - New data added by the user will be **appended** to the file.
  
- If the file **doesn’t exist**:
  - The app simply **starts with an empty state** until the user adds their first entry.
  - **No pre-loaded data** is included in any files. The user’s data is **stored and managed dynamically** as they add new items.

### **Example**:
For a user with the email `rahulkhanna0328@gmail.com`, their data would be saved in a file located at:

```bash
scheduled_data/rahulkhanna0328@gmail.com.txt
