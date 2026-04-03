import streamlit as st
st.set_page_config(page_title="Growth Manager Dashboard", page_icon="📊", layout="wide")

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date, timezone, timedelta
import time
import hashlib

SHEET_ID  = "1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE"
SHEET_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/edit"
SHEET_TAB = "Master Tasks"
MY_EMAIL  = "projects@rheumacare.com"

# ── LOGIN CONFIG ──────────────────────────────────────────────
# Credentials are loaded from Streamlit secrets.
# In secrets.toml add:
#   [users]
#   drvaisakh = "your_password"
#   admin = "another_password"
# Passwords are compared as plain text (secrets are never exposed publicly)

def get_users():
    try:
        return dict(st.secrets["users"])
    except Exception:
        # Fallback hardcoded credentials if secrets not configured
        return {
            "drvaisakh": "rheuma@2026",
            "admin":     "taskflow@admin",
        }

AUTO_REFRESH_SECONDS = 30   # how often the app auto-refreshes to pick up new tasks

CENTRES    = ["Nettoor","Kumbalam","Trivandrum","Bhubaneswar","Kannur","Changanassery","Guwahati","Kollam","Mysore","Bangalore","Ahmedabad","Visakhapatnam","Others"]
CATEGORIES = ["Civil Work","Admin / Hardware","Regulatory / Licence","IT / Systems","QMS / HMS","Operations","Finance","HR / Admin","Legal / Contracts","Other"]
STATUSES   = ["Pending","Not Started","In Progress","On Hold","Done","Rejected","Reassigned","Not Mine"]
PRIORITIES = ["","High","Medium","Low"]
SOURCES    = ["Email","Tracker","Manual","Meeting","WhatsApp"]
SHEET_COLS = ["ID","Centre","Category","Title","Due Date","Days Overdue","Status","Priority","Owner","Source","Notes","Reassigned To","Date Added","Last Updated","Email Message ID","Parent ID"]
CENTRE_COLORS = {"Nettoor":"#6366F1","Kumbalam":"#7C3AED","Trivandrum":"#059669","Bhubaneswar":"#65A30D","Kannur":"#EA580C","Changanassery":"#0891B2","Guwahati":"#2563EB","Kollam":"#0D9488","Mysore":"#D97706","Bangalore":"#DB2777","Ahmedabad":"#F59E0B","Visakhapatnam":"#DC2626","Others":"#16A34A"}
STATUS_ICON = {"Pending":"🔵","Not Started":"⚪","In Progress":"🟡","On Hold":"🟠","Done":"✅","Rejected":"❌","Reassigned":"👤","Not Mine":"🚫"}
SCOPES = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]

# Short-code → canonical centre name (used in holiday sheet)
CENTRE_CODES = {
    "tvm":   "Trivandrum",
    "amd":   "Ahmedabad",
    "bbsr":  "Bhubaneswar",
    "msr":   "Mysore",
    "vizag": "Visakhapatnam",
    "knr":   "Kannur",
    "chg":   "Changanassery",
    "guw":   "Guwahati",
    "qln":   "Kollam",
    "blr":   "Bangalore",
    # Cochin codes → both Nettoor and Kumbalam (same city)
    "chn":   ["Nettoor", "Kumbalam"],
    "cok":   ["Nettoor", "Kumbalam"],
    "kochi": ["Nettoor", "Kumbalam"],
    "cochin":["Nettoor", "Kumbalam"],
}

# State → centre(s) mapping for holiday expansion
STATE_CENTRES = {
    "kerala":         ["Nettoor","Kumbalam","Changanassery","Kollam","Kannur"],
    "karnataka":      ["Mysore","Bangalore"],
    "assam":          ["Guwahati"],
    "odisha":         ["Bhubaneswar"],
    "gujarat":        ["Ahmedabad"],
    "andhra pradesh": ["Visakhapatnam"],
    "andhra":         ["Visakhapatnam"],
    "telangana":      ["Visakhapatnam"],
    "ap":             ["Visakhapatnam"],
}

PING_SHEET_ID      = "1uf4pqKHEAbw6ny7CVZZVMw23PTfmv0QZzdCyj4fU33c"
PING_SERVERS_TAB   = "ServerStatus"
SERVER_TYPE_ORDER  = ["Main Server","Backup Server","Bitvoice Gateway","Bitvoice Server"]
SERVER_DISPLAY_COLS= ["Centre","Status","Timestamp","ResponseTime(ms)","Server IP","Last Online"]

HOLIDAY_SHEET_ID   = SHEET_ID        # Holidays tab lives in the main TaskFlow sheet
HOLIDAY_TAB        = "Holidays"
GCAL_SCOPES        = ["https://www.googleapis.com/auth/calendar"]

@st.cache_resource(ttl=300)
def get_client():
    try:
        creds = Credentials.from_service_account_info(st.secrets["gcp_service_account"], scopes=SCOPES)
        return gspread.authorize(creds)
    except Exception as e:
        st.error(f"❌ Google connection failed: {e}")
        return None

@st.cache_resource(ttl=300)
def get_ws():
    client = get_client()
    if not client: return None
    try:
        sh = client.open_by_key(SHEET_ID)
        try:
            ws = sh.worksheet(SHEET_TAB)
        except gspread.WorksheetNotFound:
            ws = sh.add_worksheet(SHEET_TAB, rows=2000, cols=20)
            ws.append_row(SHEET_COLS)
        return ws
    except Exception as e:
        st.error(f"❌ Sheet error: {e}")
        return None

@st.cache_data(ttl=30)
def load_tasks():
    ws = get_ws()
    if ws is None: return pd.DataFrame(columns=SHEET_COLS)
    try:
        records = ws.get_all_records(default_blank="")
        if not records: return pd.DataFrame(columns=SHEET_COLS)
        df = pd.DataFrame(records)
        for c in SHEET_COLS:
            if c not in df.columns: df[c] = ""
        df["Days Overdue"] = pd.to_numeric(df["Days Overdue"], errors="coerce").fillna(0).astype(int)
        df["ID"] = pd.to_numeric(df["ID"], errors="coerce").fillna(0).astype(int)
        return df
    except Exception as e:
        st.error(f"Load error: {e}")
        return pd.DataFrame(columns=SHEET_COLS)

@st.cache_data(ttl=60)
def load_servers():
    client = get_client()
    if not client: return pd.DataFrame()
    try:
        ws = client.open_by_key(PING_SHEET_ID).worksheet(PING_SERVERS_TAB)
        data = ws.get_all_records()
        if not data: return pd.DataFrame()
        df = pd.DataFrame(data)
        df.columns = df.columns.str.strip()
        return df
    except Exception as e:
        st.error(f"Server data error: {e}")
        return pd.DataFrame()

def _parse_holidays_python(raw_rows, current_year):
    """Parse holiday sheet rows with Python (no AI required).

    Supports two layouts:
      A) Centre | Date          (no holiday name column — uses "Holiday" as name)
      B) Date | Holiday Name | Centre   (full layout)

    Handles date formats: DD/MM/YYYY, DD-MM-YYYY, YYYY-MM-DD, '15 Apr 2025', serials.
    """
    from dateutil import parser as du_parser
    events = []

    if not raw_rows:
        return events

    _gs_epoch = date(1899, 12, 30)

    _FMTS = [
        "%d/%m/%Y", "%d-%m-%Y",
        "%d/%m/%y", "%d-%m-%y",
        "%Y-%m-%d",
        "%d %b %Y", "%d %B %Y",
        "%d-%b-%Y", "%d-%B-%Y",
        "%d %b %y", "%d %B %y",
    ]

    def _parse_date_val(raw):
        raw = raw.strip()
        if not raw:
            return None
        for fmt in _FMTS:
            try:
                return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
            except ValueError:
                continue
        if raw.replace(",", "").isdigit():
            try:
                return (_gs_epoch + timedelta(days=int(raw.replace(",", "")))).strftime("%Y-%m-%d")
            except Exception:
                pass
        try:
            return du_parser.parse(raw, dayfirst=True, default=datetime(current_year, 1, 1)).strftime("%Y-%m-%d")
        except Exception:
            return None

    # ── Detect columns from header row ────────────────────────────────────────
    header = [c.lower().strip() for c in raw_rows[0]]
    date_col = name_col = centre_col = reason_col = None
    for i, h in enumerate(header):
        if date_col is None and any(w in h for w in ("date", "day", "dt")):
            date_col = i
        if name_col is None and any(w in h for w in ("holiday", "name", "occasion", "event", "festival", "description", "remark")):
            name_col = i
        if centre_col is None and any(w in h for w in ("centre", "center", "clinic", "location", "state", "branch", "city", "region")):
            centre_col = i
        if reason_col is None and any(w in h for w in ("reason", "type", "note", "notes", "details")):
            reason_col = i

    # Ensure reason_col doesn't clash with already-assigned columns
    if reason_col in (date_col, name_col, centre_col):
        reason_col = None

    has_header = any(col is not None for col in (date_col, name_col, centre_col))
    data_rows  = raw_rows[1:] if has_header else raw_rows

    # ── If still unresolved, guess by sampling first data row ─────────────────
    if date_col is None or (date_col == name_col):
        sample = data_rows[0] if data_rows else []
        # whichever column parses as a date is the date column
        for i, cell in enumerate(sample):
            if _parse_date_val(cell):
                date_col = i
                break
        if date_col is None:
            date_col = 0  # last resort

    # If no name column found, fall back to using the reason column as the name
    if name_col is None or name_col == date_col or name_col == centre_col:
        if reason_col is not None and reason_col not in (date_col, centre_col):
            name_col   = reason_col  # Reason column doubles as the holiday name
            reason_col = None
        else:
            name_col = None  # will use default "Holiday"

    # ── Parse rows ────────────────────────────────────────────────────────────
    for row in data_rows:
        if not row or not any(cell.strip() for cell in row):
            continue
        date_val   = row[date_col].strip()   if date_col is not None and date_col < len(row) else ""
        name_val   = (row[name_col].strip()  if name_col is not None and name_col < len(row) else "") or "Holiday"
        centre_val = row[centre_col].strip() if centre_col is not None and centre_col < len(row) else "All"
        reason_val = row[reason_col].strip() if reason_col is not None and reason_col < len(row) else ""

        if not date_val:
            continue
        date_str = _parse_date_val(date_val)
        if not date_str:
            continue
        events.append({"date": date_str, "name": name_val, "centre": centre_val or "All", "reason": reason_val})

    return events


@st.cache_data(ttl=3600)
def load_holidays():
    """Load holidays from Holidays tab + auto-add Sundays.
    Returns (events_list, errors_list, raw_text).
    """
    events = []
    errors = []

    # ── 1. Sundays for current + next year ────────────────────────────────────
    for yr in [datetime.now().year, datetime.now().year + 1]:
        d = date(yr, 1, 1)
        while d.year == yr:
            if d.weekday() == 6:
                events.append({"date": d.strftime("%Y-%m-%d"), "name": "Sunday", "centre": "All", "reason": ""})
            d += timedelta(days=1)

    # ── 2. Open sheet — case-insensitive tab lookup ───────────────────────────
    gs_client = get_client()
    if not gs_client:
        errors.append("Google Sheets client unavailable.")
        return events, errors, ""

    try:
        sh = gs_client.open_by_key(HOLIDAY_SHEET_ID)
        ws = None
        for worksheet in sh.worksheets():
            if worksheet.title.strip().lower() == HOLIDAY_TAB.lower():
                ws = worksheet
                break
        if ws is None:
            available = ", ".join(w.title for w in sh.worksheets())
            errors.append(f"Tab '{HOLIDAY_TAB}' not found. Tabs in sheet: {available}")
            return events, errors, ""
        raw_rows = ws.get_all_values()
    except Exception as e:
        errors.append(f"Sheet read error: {type(e).__name__}: {e}")
        return events, errors, ""

    if not raw_rows:
        errors.append(f"'{HOLIDAY_TAB}' tab is empty.")
        return events, errors, ""

    raw_text = "\n".join(["\t".join(r) for r in raw_rows])

    # ── 3. Parse with Python parser ───────────────────────────────────────────
    py_events = _parse_holidays_python(raw_rows, datetime.now().year)
    if not py_events:
        errors.append(f"Parser returned 0 holidays. First row of sheet: {raw_rows[0]}")
    for item in py_events:
        for c in normalize_centre(item.get("centre", "All")):
            events.append({
                "date":   item["date"],
                "name":   item["name"],
                "centre": c,
                "reason": item.get("reason", ""),
            })

    # ── 4. Deduplicate ────────────────────────────────────────────────────────
    seen, deduped = set(), []
    for e in events:
        key = (e["date"], e["name"], e["centre"])
        if key not in seen:
            seen.add(key)
            deduped.append(e)

    return deduped, errors, raw_text

@st.cache_data(ttl=60)
def load_gcal_events(year, month):
    """Load events from the work Google Calendar for the given month."""
    try:
        from googleapiclient.discovery import build
        from google.oauth2.service_account import Credentials as SACredentials
        creds = SACredentials.from_service_account_info(
            st.secrets["gcp_service_account"], scopes=GCAL_SCOPES
        )
        service = build("calendar", "v3", credentials=creds)
        start_dt = datetime(year, month, 1, tzinfo=timezone.utc)
        end_dt   = datetime(year + (month // 12), (month % 12) + 1, 1, tzinfo=timezone.utc)
        result = service.events().list(
            calendarId=MY_EMAIL,
            timeMin=start_dt.isoformat(),
            timeMax=end_dt.isoformat(),
            singleEvents=True,
            orderBy="startTime",
            maxResults=250,
        ).execute()
        return result.get("items", [])
    except Exception:
        return []

_TASKFLOW_TAG = "[TaskFlow-Sync]"
_ACTIVE_STATUSES = {"Pending", "Not Started", "In Progress", "On Hold"}
_PRIORITY_COLOR  = {"High": "11", "Medium": "5", "Low": "2", "": "0"}  # GCal color IDs

def get_gcal_service():
    """Return an authenticated Google Calendar API service (read+write)."""
    from googleapiclient.discovery import build
    from google.oauth2.service_account import Credentials as SACredentials
    creds = SACredentials.from_service_account_info(
        st.secrets["gcp_service_account"], scopes=GCAL_SCOPES
    )
    return build("calendar", "v3", credentials=creds)

def sync_tasks_to_gcal(df) -> tuple:
    """Delete all previously synced TaskFlow events then recreate from active tasks.
    Returns (created_count, deleted_count, error_message).
    """
    try:
        service  = get_gcal_service()
        today    = date.today()
        time_min = (datetime.combine(today, datetime.min.time()) - timedelta(days=60)).isoformat() + "Z"
        time_max = (datetime.combine(today, datetime.min.time()) + timedelta(days=365)).isoformat() + "Z"

        # ── 1. Delete all previous TaskFlow sync events ──────────────────────
        deleted = 0
        page_token = None
        while True:
            resp = service.events().list(
                calendarId=MY_EMAIL,
                timeMin=time_min,
                timeMax=time_max,
                q=_TASKFLOW_TAG,
                maxResults=250,
                pageToken=page_token,
                singleEvents=True,
            ).execute()
            for ev in resp.get("items", []):
                if _TASKFLOW_TAG in (ev.get("description") or ""):
                    service.events().delete(calendarId=MY_EMAIL, eventId=ev["id"]).execute()
                    deleted += 1
            page_token = resp.get("nextPageToken")
            if not page_token:
                break

        # ── 2. Create events for active tasks ────────────────────────────────
        active = df[df["Status"].isin(_ACTIVE_STATUSES)] if not df.empty else df
        created = 0
        for _, row in active.iterrows():
            # Date: use Due Date if set, else today
            due = str(row.get("Due Date", "")).strip()
            try:
                event_date = date.fromisoformat(due) if due else today
            except ValueError:
                event_date = today

            title    = str(row.get("Title",    "")).strip() or "(No title)"
            centre   = str(row.get("Centre",   "")).strip()
            category = str(row.get("Category", "")).strip()
            priority = str(row.get("Priority", "")).strip()
            status   = str(row.get("Status",   "")).strip()
            owner    = str(row.get("Owner",    "")).strip()
            notes    = str(row.get("Notes",    "")).strip()
            task_id  = str(row.get("ID",       "")).strip()

            overdue_flag = " ⚠️" if event_date < today and status not in ("Done", "Rejected") else ""
            summary = f"[TaskFlow]{overdue_flag} {centre} | {title}"

            description = (
                f"Centre: {centre}\n"
                f"Category: {category}\n"
                f"Priority: {priority}\n"
                f"Status: {status}\n"
                f"Owner: {owner}\n"
                f"Due: {due or 'Not set'}\n"
            )
            if notes:
                description += f"\nNotes: {notes}\n"
            description += f"\nTask ID: {task_id}\n{_TASKFLOW_TAG}"

            event_body = {
                "summary":     summary,
                "description": description,
                "start":       {"date": event_date.isoformat()},
                "end":         {"date": event_date.isoformat()},
                "colorId":     _PRIORITY_COLOR.get(priority, "0"),
            }
            service.events().insert(calendarId=MY_EMAIL, body=event_body).execute()
            created += 1

        return created, deleted, None
    except Exception as e:
        return 0, 0, str(e)

def save_task(task):
    ws = get_ws()
    if not ws: return False
    try:
        ws.append_row([task.get(c,"") for c in SHEET_COLS], value_input_option="USER_ENTERED")
        load_tasks.clear(); return True
    except Exception as e:
        st.error(f"Save failed: {e}"); return False

def save_holiday(hol_date: str, hol_name: str, centres: list, reason: str = "") -> bool:
    """Append one row per centre to the Holidays sheet tab.
    Creates a header row if the sheet is empty.
    """
    gs_client = get_client()
    if not gs_client:
        st.error("Google Sheets client unavailable.")
        return False
    try:
        sh = gs_client.open_by_key(HOLIDAY_SHEET_ID)
        try:
            ws = sh.worksheet(HOLIDAY_TAB)
        except Exception:
            ws = sh.add_worksheet(HOLIDAY_TAB, rows=500, cols=5)
        existing = ws.get_all_values()
        if not existing:
            ws.append_row(["Date", "Holiday Name", "Centre", "Reason"], value_input_option="USER_ENTERED")
        for centre in centres:
            ws.append_row([hol_date, hol_name, centre, reason], value_input_option="USER_ENTERED")
        load_holidays.clear()
        return True
    except Exception as e:
        st.error(f"Holiday save failed: {e}")
        return False

def delete_holiday_rows(hol_date: str, hol_name: str, centres: list) -> int:
    """Delete rows from the Holidays sheet matching (date, name, centre).
    Returns number of rows deleted, or -1 on error.
    """
    gs_client = get_client()
    if not gs_client:
        st.error("Google Sheets client unavailable.")
        return -1
    try:
        sh  = gs_client.open_by_key(HOLIDAY_SHEET_ID)
        ws  = sh.worksheet(HOLIDAY_TAB)
        all_rows = ws.get_all_values()
        if not all_rows:
            return 0

        header = [c.lower().strip() for c in all_rows[0]]
        has_header = any(w in h for h in header for w in ("date", "holiday", "name", "centre"))
        data_start = 1 if has_header else 0

        def _col(keywords):
            for i, h in enumerate(header):
                if any(w in h for w in keywords):
                    return i
            return None

        date_col   = _col(("date", "day", "dt"))    or 0
        name_col   = _col(("holiday", "name", "occasion", "festival", "event")) or 1
        centre_col = _col(("centre", "center", "clinic", "location", "state", "branch")) or 2

        rows_to_delete = []
        for idx, row in enumerate(all_rows[data_start:], start=data_start + 1):
            r_date   = row[date_col].strip()   if date_col   < len(row) else ""
            r_name   = row[name_col].strip()   if name_col   < len(row) else ""
            r_centre = row[centre_col].strip() if centre_col < len(row) else "All"
            if r_date == hol_date and r_name == hol_name:
                if r_centre in centres or (r_centre == "All" and "All" in centres):
                    rows_to_delete.append(idx)

        for idx in sorted(rows_to_delete, reverse=True):
            ws.delete_rows(idx)

        load_holidays.clear()
        return len(rows_to_delete)
    except Exception as e:
        st.error(f"Delete failed: {e}")
        return -1

def update_field(tid, field, value):
    ws = get_ws()
    if not ws: return False
    try:
        cell = ws.find(str(tid), in_column=1)
        ws.update_cell(cell.row, SHEET_COLS.index(field)+1, value)
        ws.update_cell(cell.row, SHEET_COLS.index("Last Updated")+1, datetime.now().strftime("%Y-%m-%d %H:%M"))
        load_tasks.clear(); return True
    except Exception as e:
        st.error(f"Update failed: {e}"); return False

def delete_row(tid):
    ws = get_ws()
    if not ws: return False
    try:
        cell = ws.find(str(tid), in_column=1)
        ws.delete_rows(cell.row); load_tasks.clear(); return True
    except: return False

def set_parent(child_id, parent_id):
    """Set or clear Parent ID on a task. Pass parent_id="" to unlink."""
    return update_field(child_id, "Parent ID", str(parent_id) if parent_id else "")

def find_duplicate_groups(tasks_df):
    """Use Claude AI to find groups of similar/duplicate tasks. Returns list of {parent_id, child_ids}."""
    import json, re
    client = get_anthropic_client()
    if not client or tasks_df.empty:
        return []
    task_list = "\n".join([
        f"ID:{int(r['ID'])} Centre:{r['Centre']} | {str(r['Title'])[:120]}"
        for _, r in tasks_df.iterrows()
    ])
    prompt = f"""You are reviewing tasks for a healthcare clinic chain manager. Identify groups of tasks that appear to be about the SAME underlying issue — likely created because multiple people sent separate emails about it.

Return ONLY a raw JSON array. Each element: {{"parent_id": <keep this as main>, "child_ids": [<link these under parent>]}}
If no duplicates found, return [].

Tasks:
{task_list}"""
    try:
        resp = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1000,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = re.sub(r'^```(?:json)?', '', resp.content[0].text.strip()).rstrip('`').strip()
        result = json.loads(raw)
        return result if isinstance(result, list) else []
    except Exception:
        return []

CENTRE_KEYWORDS_PY = {
    "Nettoor":       ["nettoor","nettur"],
    "Kumbalam":      ["kumbalam","kbl"],
    "Trivandrum":    ["trivandrum","thiruvananthapuram","tvm"],
    "Bhubaneswar":   ["bhubaneswar","bbsr","bhubaneshwar","odisha"],
    "Kannur":        ["kannur","cannanore","knn"],
    "Changanassery": ["changanassery","chengannur","cgs"],
    "Guwahati":      ["guwahati","gauhati","guw"],
    "Kollam":        ["kollam","quilon","qln"],
    "Mysore":        ["mysore","mysuru","mys"],
    "Bangalore":     ["bangalore","bengaluru","blr"],
    "Ahmedabad":     ["ahmedabad","gujarat","ahd"],
    "Visakhapatnam": ["visakhapatnam","vizag","vsk","vsp","vishakhapatnam"],
}
CATEGORY_KEYWORDS_PY = {
    "Civil Work":           ["civil","construction","partition","lab","room","floor","building","renovation"],
    "IT / Systems":         ["server","internet","wifi","bsnl","airtel","jio","network","ip","vpn","router","switch","laptop","computer","cctv","ups","smps"],
    "Finance":              ["payment","invoice","bill","advance","reimburs","gst","amount","rs.","rupee","lakh","fees","salary"],
    "Regulatory / Licence": ["noc","licence","license","nabl","nabh","drug","compliance","inspection","statutory","registration"],
    "Admin / Hardware":     ["printer","ac","inverter","hardware","equipment","furniture","chair","table","barcode","scanner"],
    "Legal / Contracts":    ["lease","agreement","contract","deed","registrar","legal","lawyer"],
    "QMS / HMS":            ["qms","hms","emr","token","display","impactin","software","module"],
    "Operations":           ["sop","cash","petty","operations","daily","report","attendance"],
}

def detect_centre(text):
    t = text.lower()
    for centre, kws in CENTRE_KEYWORDS_PY.items():
        if any(kw in t for kw in kws):
            return centre
    return "Others"

def detect_category(text):
    t = text.lower()
    for cat, kws in CATEGORY_KEYWORDS_PY.items():
        if any(kw in t for kw in kws):
            return cat
    return "Operations"

def detect_priority(text):
    t = text.lower()
    if any(w in t for w in ["urgent","asap","immediately","critical","today","high priority","important"]):
        return "High"
    if any(w in t for w in ["soon","this week","priority","medium"]):
        return "Medium"
    return "Medium"

def normalize_centre(s):
    """Map a centre code / abbreviation / state name to a list of canonical centre names."""
    sl = s.lower().strip()
    if sl in ("all", "", "all centres", "all centers", "pan india", "national"):
        return ["All"]
    # Short code match (TVM, AMD, CHN, …)
    if sl in CENTRE_CODES:
        v = CENTRE_CODES[sl]
        return v if isinstance(v, list) else [v]
    # Exact match
    for c in CENTRES:
        if c.lower() == sl:
            return [c]
    # State → multiple centres
    for state, centres in STATE_CENTRES.items():
        if state in sl:
            return centres
    # Keyword match (uses same dict as task detection)
    for centre, kws in CENTRE_KEYWORDS_PY.items():
        if any(kw in sl for kw in kws):
            return [centre]
    return ["All"]  # unknown code → treat as all-centre holiday

def _get_anthropic_key():
    """Try all known secret paths for the Anthropic API key."""
    for getter in [
        lambda: st.secrets["ANTHROPIC_API_KEY"],
        lambda: st.secrets["anthropic"]["api_key"],
        lambda: st.secrets["gcp_service_account"]["ANTHROPIC_API_KEY"],
    ]:
        try:
            v = getter()
            if v:
                return v
        except Exception:
            continue
    return None

@st.cache_resource
def get_anthropic_client():
    try:
        import anthropic
        key = _get_anthropic_key()
        if not key:
            return None
        return anthropic.Anthropic(api_key=key)
    except Exception:
        return None

def parse_tasks_with_ai(text):
    import json, re
    client = get_anthropic_client()
    if not client:
        # Fallback: single task via keyword detection
        return [{
            "title": re.split(r'[.\n!]', text.strip())[0][:180].strip(),
            "centre": detect_centre(text),
            "category": detect_category(text),
            "priority": detect_priority(text),
            "notes": text.strip(),
        }]

    prompt = f"""You are a task extraction assistant for Dr. Vaisakh VS, Growth Manager at RheumaCARE (multi-centre rheumatology clinic chain in India).

Extract EVERY distinct actionable task from the message below. If there are multiple tasks, return one entry per task. If there is only one task, return a single-element array.

Return ONLY a raw JSON array — no explanation, no markdown fences:
[
  {{
    "title": "short actionable verb-first title, max 150 chars",
    "centre": "exactly one of: Nettoor, Kumbalam, Trivandrum, Bhubaneswar, Kannur, Changanassery, Guwahati, Kollam, Mysore, Bangalore, Ahmedabad, Visakhapatnam, Others",
    "category": "exactly one of: Civil Work, Admin / Hardware, Regulatory / Licence, IT / Systems, QMS / HMS, Operations, Finance, HR / Admin, Legal / Contracts, Other",
    "priority": "High, Medium, or Low",
    "notes": "key context — who asked, amounts, deadlines, any specifics"
  }}
]

Message:
{text}"""

    try:
        import anthropic
        resp = get_anthropic_client().messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=1500,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = resp.content[0].text.strip()
        # Strip markdown code fences if model includes them
        raw = re.sub(r'^```(?:json)?', '', raw).rstrip('`').strip()
        tasks = json.loads(raw)
        valid_centres = set(CENTRES)
        valid_cats    = set(CATEGORIES)
        for t in tasks:
            if t.get("centre")   not in valid_centres: t["centre"]   = detect_centre(text)
            if t.get("category") not in valid_cats:    t["category"] = detect_category(text)
            if t.get("priority") not in ["High","Medium","Low"]: t["priority"] = "Medium"
        return tasks
    except Exception as e:
        st.warning(f"AI parsing error ({e}). Using keyword fallback.")
        return [{
            "title": re.split(r'[.\n!]', text.strip())[0][:180].strip(),
            "centre": detect_centre(text),
            "category": detect_category(text),
            "priority": detect_priority(text),
            "notes": text.strip(),
        }]

def next_id(df):
    if df.empty: return 1
    ids = pd.to_numeric(df["ID"], errors="coerce").dropna()
    return int(ids.max())+1 if len(ids) else 1

def css():
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@700&display=swap');
    html,body,[class*="css"]{font-family:'DM Sans',sans-serif!important}
    [data-testid="stSidebar"]{background:#14172080;border-right:1px solid rgba(255,255,255,.06)}
    .block-container{padding-top:0.5rem!important;padding-bottom:0.5rem!important;max-width:100%!important}
    .tc{background:#1C2030;border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px 13px;margin-bottom:6px;border-left:4px solid #2563EB}
    .tc.ov{border-left-color:#EF4444}.tc.hold{border-left-color:#F59E0B}.tc.reg{border-left-color:#8B5CF6}.tc.qms{border-left-color:#EC4899}.tc.done{opacity:.38;border-left-color:#4B5563}.tc.notmine{opacity:.25;border-left-color:#374151;filter:grayscale(.9)}
    .ttl{font-size:13px;font-weight:500;color:#E8EAFF;line-height:1.35;margin-bottom:5px}
    .ttl.done{text-decoration:line-through;color:#6B7280}
    .tmeta{font-size:11px;color:#7880A4;display:flex;flex-wrap:wrap;gap:4px;align-items:center}
    .bdg{display:inline-block;font-size:9px;font-weight:700;padding:2px 6px;border-radius:20px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap}
    .ov_{background:rgba(239,68,68,.15);color:#F87171}.pd_{background:rgba(37,99,235,.15);color:#93C5FD}
    .hd_{background:rgba(245,158,11,.15);color:#FCD34D}.dn_{background:rgba(52,211,153,.15);color:#6EE7B7}
    .rj_{background:rgba(239,68,68,.1);color:#FCA5A5}.rg_{background:rgba(139,92,246,.15);color:#C4B5FD}
    .qm_{background:rgba(236,72,153,.15);color:#F9A8D4}.hi_{background:rgba(245,158,11,.12);color:#FCD34D}
    .em_{background:rgba(20,184,166,.15);color:#5EEAD4}.tr_{background:rgba(99,102,241,.15);color:#A5B4FC}
    .ct_{background:rgba(120,128,164,.15);color:#9CA3AF}
    .lk_{background:rgba(52,211,153,.15);color:#34D399}
    .ch{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#7880A4;padding:5px 0 4px;border-bottom:1px solid rgba(255,255,255,.05);margin:12px 0 7px}
    .mrow{display:flex;gap:8px;margin-bottom:10px;flex-wrap:nowrap}
    .met{background:#1C2030;border:1px solid rgba(255,255,255,.07);border-radius:10px;padding:9px 12px;flex:1;min-width:60px;text-align:center}
    .mn{font-family:'JetBrains Mono',monospace;font-size:20px;font-weight:700}
    .ml{font-size:9px;color:#7880A4;text-transform:uppercase;letter-spacing:.5px;margin-top:2px}
    .stButton>button{border-radius:6px!important;font-size:11px!important;padding:2px 7px!important}
    .stTabs [data-baseweb="tab-list"]{gap:4px!important}
    .stTabs [data-baseweb="tab"]{padding:12px 18px!important;font-size:14px!important;min-height:48px!important;border-radius:8px 8px 0 0!important;cursor:pointer!important;-webkit-tap-highlight-color:transparent!important}
    .stTabs [data-baseweb="tab"]:active{opacity:.75!important}
    h1,h2,h3{margin-top:0.4rem!important;margin-bottom:0.3rem!important}
    </style>""", unsafe_allow_html=True)
    # Auto-refresh via Streamlit's built-in rerun after delay
    st.markdown(f"""<script>
    var tf_timer = setTimeout(function(){{
        var btns = window.parent.document.querySelectorAll('button');
        btns.forEach(function(b){{ if(b.innerText.includes('Refresh Now')) b.click(); }});
    }}, {AUTO_REFRESH_SECONDS * 1000});
    </script>""", unsafe_allow_html=True)

def task_card(row, pfx="", is_child=False):
    status  = str(row.get("Status","")).strip()
    overdue = int(row.get("Days Overdue",0))
    cat     = str(row.get("Category",""))
    src     = str(row.get("Source","")).lower()
    pri     = str(row.get("Priority","")).strip()
    centre  = str(row.get("Centre",""))
    title   = str(row.get("Title",""))
    tid     = int(row.get("ID",0))
    owner   = str(row.get("Owner",""))
    due     = str(row.get("Due Date",""))
    notes   = str(row.get("Notes",""))
    reassign= str(row.get("Reassigned To",""))
    parent_id = str(row.get("Parent ID","")).strip()
    is_done    = status in ["Done","Rejected"]
    is_notmine = status == "Not Mine"
    clr     = CENTRE_COLORS.get(centre,"#2563EB")

    # Find children of this task (only for top-level cards)
    df_all = load_tasks()
    children = df_all[df_all["Parent ID"].astype(str).str.strip() == str(tid)] if (not is_child and not df_all.empty) else pd.DataFrame()
    has_children = not children.empty

    cc = "tc"
    if is_notmine:            cc += " notmine"
    elif is_done:             cc += " done"
    elif "Regulatory" in cat: cc += " reg"
    elif "QMS" in cat:        cc += " qms"
    elif status=="On Hold":   cc += " hold"
    elif overdue>0:           cc += " ov"

    if is_notmine:    sb = '<span class="bdg ct_">🚫 Not Mine</span>'
    elif is_done:     sb = f'<span class="bdg dn_">{STATUS_ICON.get(status,"")} {status}</span>'
    elif status=="On Hold": sb = '<span class="bdg hd_">⏸ On Hold</span>'
    elif overdue>0:   sb = f'<span class="bdg ov_">▲ {overdue}d late</span>'
    elif "Regulatory" in cat: sb = '<span class="bdg rg_">⚖ Regulatory</span>'
    elif "QMS" in cat:sb = '<span class="bdg qm_">⚙ QMS/HMS</span>'
    else:             sb = '<span class="bdg pd_">● Pending</span>'

    s2 = f'<span class="bdg em_">✉ Email</span>'     if src=="email"   else \
         f'<span class="bdg tr_">📊 Tracker</span>'  if src=="tracker" else \
         f'<span class="bdg ct_">{src.title()}</span>' if src else ""
    pb  = '<span class="bdg hi_">★ High</span>'       if pri=="High" else ""
    cb  = f'<span class="bdg ct_">{cat}</span>'        if cat else ""
    db  = f'<span>📅 {due}</span>'                     if due else ""
    ob  = f'<span>👤 {owner}</span>'                   if owner and owner!="Dr. Vaisakh V S" else ""
    rb  = f'<span>↪ {reassign}</span>'                 if reassign else ""
    glb = f'<span class="bdg lk_">🔗 {len(children)} linked</span>' if has_children else ""
    slb = '<span class="bdg lk_">↳ sub-task</span>'   if parent_id else ""
    tc  = "ttl done" if (is_done or is_notmine) else "ttl"

    st.markdown(f"""<div class="{cc}" style="border-left-color:{clr}">
        <div class="{tc}">{title}</div>
        <div class="tmeta">{sb}{s2}{pb}{cb}{db}{ob}{rb}{glb}{slb}</div>
    </div>""", unsafe_allow_html=True)

    if is_notmine:
        c1,c2 = st.columns([1,5])
        if c1.button("↩ Reactivate", key=f"rm_{pfx}{tid}"): update_field(tid,"Status","Pending"); st.rerun()
        c_edit = st.columns([1,5])[0]
        if c_edit.button("✏️ Centre", key=f"ec_{pfx}{tid}"):
            st.session_state[f"ce_{pfx}{tid}"] = not st.session_state.get(f"ce_{pfx}{tid}", False)
        if st.session_state.get(f"ce_{pfx}{tid}"):
            cur_idx = CENTRES.index(centre) if centre in CENTRES else 0
            new_centre = st.selectbox("Change centre to:", CENTRES, index=cur_idx, key=f"cs_{pfx}{tid}")
            if st.button("Update Centre", key=f"cu_{pfx}{tid}"):
                update_field(tid, "Centre", new_centre)
                st.session_state[f"ce_{pfx}{tid}"] = False; st.rerun()
        if notes:
            with st.expander("📝 Notes"): st.caption(notes)
    elif not is_done:
        c1,c2,c3 = st.columns(3)
        if c1.button("✅ Done",   key=f"d_{pfx}{tid}"): update_field(tid,"Status","Done");     st.rerun()
        if c2.button("⏸ Hold",   key=f"h_{pfx}{tid}"): update_field(tid,"Status","On Hold");  st.rerun()
        if c3.button("❌ Reject", key=f"r_{pfx}{tid}"): update_field(tid,"Status","Rejected"); st.rerun()
        c4,c5,c6,c7 = st.columns(4)
        if c4.button("🚫 Not Mine", key=f"nm_{pfx}{tid}"): update_field(tid,"Status","Not Mine"); st.rerun()
        if c5.button("👤 Assign",   key=f"a_{pfx}{tid}"):
            st.session_state[f"rs_{pfx}{tid}"] = not st.session_state.get(f"rs_{pfx}{tid}",False)
        if c6.button("✏️ Centre",   key=f"ec_{pfx}{tid}"):
            st.session_state[f"ce_{pfx}{tid}"] = not st.session_state.get(f"ce_{pfx}{tid}", False)
        if c7.button("🗑 Delete",   key=f"x_{pfx}{tid}"): delete_row(tid); st.rerun()
        if st.session_state.get(f"rs_{pfx}{tid}"):
            nm = st.text_input("Reassign to:", key=f"rn_{pfx}{tid}", placeholder="Name / email")
            if st.button("Confirm →", key=f"rc_{pfx}{tid}"):
                update_field(tid,"Status","Reassigned"); update_field(tid,"Reassigned To",nm)
                st.session_state[f"rs_{tid}"] = False; st.rerun()
        if st.session_state.get(f"ce_{pfx}{tid}"):
            cur_idx = CENTRES.index(centre) if centre in CENTRES else 0
            new_centre = st.selectbox("Change centre to:", CENTRES, index=cur_idx, key=f"cs_{pfx}{tid}")
            if st.button("Update Centre", key=f"cu_{pfx}{tid}"):
                update_field(tid, "Centre", new_centre)
                st.session_state[f"ce_{pfx}{tid}"] = False; st.rerun()
        # ── Grouping controls ─────────────────────────────────────
        if is_child and parent_id:
            if st.button("🔓 Unlink from parent", key=f"ul_{pfx}{tid}"):
                set_parent(tid, ""); st.rerun()
        elif not is_child:
            if st.button("🔗 Link to parent task", key=f"lk_{pfx}{tid}"):
                st.session_state[f"lnk_{pfx}{tid}"] = not st.session_state.get(f"lnk_{pfx}{tid}", False)
            if st.session_state.get(f"lnk_{pfx}{tid}"):
                this_centre    = str(row.get("Centre", "")).strip()
                active_statuses = {"Pending", "Not Started", "In Progress", "On Hold"}
                eligible = df_all[
                    (df_all["ID"] != tid) &
                    (df_all["Parent ID"].astype(str).str.strip() == "") &
                    (df_all["Centre"].astype(str).str.strip() == this_centre) &
                    (df_all["Status"].isin(active_statuses))
                ]
                opts = {f"#{int(r['ID'])}: {str(r['Title'])[:70]}": int(r['ID']) for _, r in eligible.iterrows()}
                if opts:
                    sel = st.selectbox("Set as sub-task of:", list(opts.keys()), key=f"lks_{pfx}{tid}")
                    if st.button("Confirm Link", key=f"lkc_{pfx}{tid}"):
                        set_parent(tid, opts[sel])
                        st.session_state[f"lnk_{pfx}{tid}"] = False; st.rerun()
                else:
                    st.info("No eligible parent tasks found.")
        if notes:
            with st.expander("📝 Notes"): st.caption(notes)

    # Show linked sub-tasks collapsed under parent
    if has_children:
        with st.expander(f"↳ {len(children)} linked task(s)", expanded=False):
            for _, child_row in children.iterrows():
                task_card(child_row, pfx=f"sub_{pfx}", is_child=True)

    st.markdown('<div style="height:3px"></div>', unsafe_allow_html=True)

def login_screen():
    """Show login screen. Returns True if already authenticated."""
    if st.session_state.get("authenticated"):
        return True

    col1, col2, col3 = st.columns([1, 1.1, 1])
    with col2:
        st.markdown("""
        <div style="text-align:center;padding:16px 0 12px">
            <div style="font-size:52px">📊</div>
            <div style="font-size:26px;font-weight:700;color:#E8EAFF;margin:10px 0 4px">Growth Manager Dashboard</div>
            <div style="font-size:13px;color:#7880A4">RheumaCARE · Dr. Vaisakh VS</div>
        </div>""", unsafe_allow_html=True)

        with st.form("login"):
            username = st.text_input("👤 Username", placeholder="Enter username")
            password = st.text_input("🔒 Password", type="password", placeholder="Enter password")
            if st.form_submit_button("Sign In →", use_container_width=True, type="primary"):
                users = get_users()
                if username in users and users[username] == password:
                    st.session_state["authenticated"] = True
                    st.session_state["username"] = username
                    st.rerun()
                else:
                    st.error("❌ Invalid username or password")

        st.markdown('<div style="text-align:center;font-size:11px;color:#40465C;margin-top:16px">Tasks sync from Gmail automatically every 30 min</div>', unsafe_allow_html=True)
    return False


# ── Calendar helpers (module-level so they can be used anywhere) ──────────────
_COCHIN = {"Nettoor", "Kumbalam"}

def _is_saturday(d_str: str) -> bool:
    try:
        return date.fromisoformat(d_str).weekday() == 5
    except ValueError:
        return False

def _display_centres(centres: list) -> list:
    """Collapse Nettoor + Kumbalam → 'Cochin' for display titles."""
    s = set(centres)
    if _COCHIN.issubset(s):
        s = (s - _COCHIN) | {"Cochin"}
    return sorted(s - {"All"}) + (["All"] if "All" in s else [])


def main():
    css()

    # ── LOGIN GATE ────────────────────────────────────────────
    if not login_screen():
        return

    # ── AUTO REFRESH every 30 seconds ────────────────────────
    if "last_refresh" not in st.session_state:
        st.session_state["last_refresh"] = time.time()
    elapsed   = time.time() - st.session_state["last_refresh"]
    remaining = max(0, int(AUTO_REFRESH_SECONDS - elapsed))
    if elapsed >= AUTO_REFRESH_SECONDS:
        load_tasks.clear()
        st.session_state["last_refresh"] = time.time()
        st.rerun()

    # ── SIDEBAR ───────────────────────────────────────────────
    with st.sidebar:
        st.markdown("**📊 Growth Manager**")
        st.caption(f"👤 **{st.session_state.get('username','')}")
        st.caption(f"[Open Sheet ↗]({SHEET_URL})")
        st.divider()
        st.markdown("**🔍 Filter**")
        sel_c = st.multiselect("Centres",  CENTRES,    default=[])
        sel_s = st.multiselect("Status",   STATUSES,   default=[])
        sel_k = st.multiselect("Category", CATEGORIES, default=[])
        sel_p = st.multiselect("Priority", ["High","Medium","Low"], default=[])
        srch  = st.text_input("🔎 Search", placeholder="Search anything...")
        st.divider()
        st.markdown("**📧 Gmail Monitor**")
        st.success("Auto-scanning via Apps Script every 30 min ✅")
        IST = timezone(timedelta(hours=5, minutes=30))
        next_refresh_ist = datetime.fromtimestamp(st.session_state["last_refresh"] + AUTO_REFRESH_SECONDS, tz=IST)
        st.caption(f"🔄 Next refresh at **{next_refresh_ist.strftime('%I:%M:%S %p')} IST**")
        col_r, col_l = st.columns(2)
        with col_r:
            if st.button("🔄 Refresh Now", use_container_width=True):
                load_tasks.clear(); get_ws.clear()
                st.session_state["last_refresh"] = time.time()
                st.rerun()
        with col_l:
            if st.button("🚪 Logout", use_container_width=True):
                st.session_state["authenticated"] = False
                st.session_state["username"] = ""
                st.rerun()
        st.divider()
        df_all = load_tasks()
        if not df_all.empty:
            st.download_button("📥 Export CSV", df_all.to_csv(index=False),
                               "TaskFlow.csv","text/csv", use_container_width=True)

    df = load_tasks()
    filt = df.copy()
    if sel_c: filt = filt[filt["Centre"].isin(sel_c)]
    if sel_s: filt = filt[filt["Status"].isin(sel_s)]
    if sel_k: filt = filt[filt["Category"].isin(sel_k)]
    if sel_p: filt = filt[filt["Priority"].isin(sel_p)]
    if srch:
        mask = filt.apply(lambda r: srch.lower() in str(r).lower(), axis=1)
        filt = filt[mask]

    st.markdown(f'<div style="font-size:17px;font-weight:700;color:#E8EAFF;margin-bottom:2px">📊 Growth Manager Dashboard <span style="font-size:11px;font-weight:400;color:#7880A4;margin-left:8px">Dr. Vaisakh VS · RheumaCARE · {datetime.now().strftime("%d %b %Y, %H:%M")}</span></div>', unsafe_allow_html=True)

    if not df.empty:
        ov = len(df[(df["Days Overdue"]>0)&(~df["Status"].isin(["Done","Rejected","Not Mine"]))])
        pd_= len(df[df["Status"].isin(["Pending","Not Started","In Progress"])])
        hd = len(df[df["Status"]=="On Hold"])
        dn = len(df[df["Status"].isin(["Done","Rejected"])])
        ac = len(df[~df["Status"].isin(["Done","Rejected","Not Mine"])])
        st.markdown(f"""<div class="mrow">
          <div class="met"><div class="mn" style="color:#E8EAFF">{ac}</div><div class="ml">Active</div></div>
          <div class="met"><div class="mn" style="color:#F87171">{ov}</div><div class="ml">Overdue</div></div>
          <div class="met"><div class="mn" style="color:#93C5FD">{pd_}</div><div class="ml">Pending</div></div>
          <div class="met"><div class="mn" style="color:#FCD34D">{hd}</div><div class="ml">On Hold</div></div>
          <div class="met"><div class="mn" style="color:#6EE7B7">{dn}</div><div class="ml">Done</div></div>
        </div>""", unsafe_allow_html=True)

    t1,t2,t3,t4,t5,t6,t7 = st.tabs(["🗂️ Active","🔴 Overdue","📊 By Centre","➕ Add Task","📈 Analytics","🖥️ Server Monitor","📅 Calendar"])

    # IDs of tasks that are sub-tasks — excluded from top-level display
    child_ids = set(df[df["Parent ID"].astype(str).str.strip() != ""]["ID"].tolist()) if not df.empty else set()

    with t1:
        active = filt[~filt["Status"].isin(["Done","Rejected","On Hold","Not Mine"])]
        # ── AI duplicate finder ───────────────────────────────────
        with st.expander("🤖 Find Duplicate / Similar Tasks", expanded=False):
            st.caption("AI scans active task titles and suggests which ones may be duplicates (same issue, multiple senders).")
            if st.button("🔍 Scan for Duplicates", key="dup_scan"):
                scan_df = active[~active["ID"].isin(child_ids)][["ID","Title","Centre","Category"]].head(100)
                with st.spinner("Scanning with AI..."):
                    st.session_state["dup_suggestions"] = find_duplicate_groups(scan_df)
            suggestions = st.session_state.get("dup_suggestions", [])
            if suggestions:
                st.markdown(f"**{len(suggestions)} potential group(s) found — review and accept:**")
                to_remove = []
                for i, grp in enumerate(suggestions):
                    pid   = grp.get("parent_id")
                    cids  = grp.get("child_ids", [])
                    p_row = df[df["ID"] == pid]
                    if p_row.empty: to_remove.append(i); continue
                    p_title = p_row.iloc[0]["Title"]
                    st.markdown(f"**Group {i+1}:** Keep **#{pid}: {p_title[:80]}** as main")
                    for cid in cids:
                        c_row = df[df["ID"] == cid]
                        c_title = c_row.iloc[0]["Title"] if not c_row.empty else f"#{cid}"
                        st.markdown(f"&nbsp;&nbsp;↳ link **#{cid}: {c_title[:80]}**")
                    ga, gs = st.columns(2)
                    if ga.button("✅ Accept", key=f"dup_acc_{i}"):
                        for cid in cids: set_parent(cid, pid)
                        st.session_state["dup_suggestions"] = [s for j,s in enumerate(suggestions) if j != i]
                        st.rerun()
                    if gs.button("⏭ Skip", key=f"dup_skip_{i}"):
                        st.session_state["dup_suggestions"] = [s for j,s in enumerate(suggestions) if j != i]
                        st.rerun()
                if not suggestions:
                    st.success("No duplicate groups found.")
            elif "dup_suggestions" in st.session_state:
                st.success("✅ No more suggestions.")
        # ── Task list (top-level only) ────────────────────────────
        top_active = active[~active["ID"].isin(child_ids)]
        if top_active.empty:
            st.success("🎉 No active tasks!")
        else:
            for centre in CENTRES:
                cdf = top_active[top_active["Centre"]==centre]
                if cdf.empty: continue
                clr = CENTRE_COLORS.get(centre,"#2563EB")
                st.markdown(f'<div class="ch" style="color:{clr}">🏥 {centre.upper()} · {len(cdf)} active</div>', unsafe_allow_html=True)
                for _,row in cdf.sort_values(["Days Overdue","Priority"],ascending=[False,True]).iterrows():
                    task_card(row, pfx="t1_")

    with t2:
        odf = filt[(filt["Days Overdue"]>0)&(~filt["Status"].isin(["Done","Rejected"]))&(~filt["ID"].isin(child_ids))].sort_values("Days Overdue",ascending=False)
        if odf.empty: st.success("🎉 No overdue tasks!")
        else:
            st.error(f"⚠️ {len(odf)} overdue — most critical first")
            for _,row in odf.iterrows(): task_card(row, pfx="t2_")

    with t3:
        smry = []
        for c in CENTRES:
            cdf = df[(df["Centre"]==c) & (~df["ID"].isin(child_ids))]
            if cdf.empty: continue
            smry.append({"Centre":c,"Active":len(cdf[~cdf["Status"].isin(["Done","Rejected"])]),"Overdue":len(cdf[(cdf["Days Overdue"]>0)&(~cdf["Status"].isin(["Done","Rejected"]))]),"Pending":len(cdf[cdf["Status"].isin(["Pending","Not Started"])]),"Hold":len(cdf[cdf["Status"]=="On Hold"]),"Done":len(cdf[cdf["Status"].isin(["Done","Rejected"])]),"Total":len(cdf)})
        if smry:
            st.dataframe(pd.DataFrame(smry), use_container_width=True, hide_index=True)
            st.divider()
            pick = st.selectbox("Drill into centre:", CENTRES)
            pdf  = filt[(filt["Centre"]==pick) & (~filt["ID"].isin(child_ids))]
            if not pdf.empty:
                for _,row in pdf.sort_values("Days Overdue",ascending=False).iterrows(): task_card(row, pfx="t3_")
            else: st.info(f"No tasks for {pick}.")

    with t4:
        # ── AI QUICK ADD (WhatsApp / Email) ──────────────────────
        has_ai = get_anthropic_client() is not None
        ai_label = "🤖 Parse with AI" if has_ai else "🔍 Detect Tasks"
        ai_hint  = "Claude AI will identify every task, assign centre/category/priority, and split into separate tasks." if has_ai \
                   else "Add ANTHROPIC_API_KEY to Streamlit secrets to enable AI parsing. Using keyword detection for now."

        with st.expander("📱 Quick Add from WhatsApp / Email", expanded=False):
            st.caption(ai_hint)
            wa_msg = st.text_area("Paste message here", height=140,
                                  placeholder="Paste any WhatsApp message or email body — even if it contains multiple tasks...")
            pc1, pc2 = st.columns([2,1])
            with pc1:
                parse_clicked = st.button(ai_label, key="wa_parse", use_container_width=True, type="primary")
            with pc2:
                if st.button("✕ Clear", key="wa_clear", use_container_width=True):
                    st.session_state["wa_parsed"] = []
                    st.rerun()

            if parse_clicked:
                if wa_msg.strip():
                    with st.spinner("Parsing…"):
                        st.session_state["wa_parsed"] = parse_tasks_with_ai(wa_msg.strip())
                        st.session_state["wa_src"]    = wa_msg.strip()
                else:
                    st.warning("Paste a message first.")

            parsed = st.session_state.get("wa_parsed", [])
            if parsed:
                n = len(parsed)
                st.markdown(f"**{n} task{'s' if n>1 else ''} detected** — review, edit, then add:")
                selected = []
                for i, task in enumerate(parsed):
                    with st.container():
                        inc = st.checkbox(f"Include task {i+1}", value=True, key=f"wa_inc_{i}")
                        if inc:
                            r1, r2, r3, r4 = st.columns([4, 2, 2, 1])
                            with r1:
                                ti = st.text_input("Title", value=task.get("title",""), key=f"wa_ti_{i}")
                            with r2:
                                ci_default = CENTRES.index(task["centre"]) if task.get("centre") in CENTRES else 0
                                ce = st.selectbox("Centre", CENTRES, index=ci_default, key=f"wa_ce_{i}")
                            with r3:
                                ca_default = CATEGORIES.index(task["category"]) if task.get("category") in CATEGORIES else 0
                                ca = st.selectbox("Category", CATEGORIES, index=ca_default, key=f"wa_ca_{i}")
                            with r4:
                                pr = st.selectbox("Priority", ["High","Medium","Low"],
                                                  index=["High","Medium","Low"].index(task.get("priority","Medium")),
                                                  key=f"wa_pr_{i}")
                            selected.append({"title":ti,"centre":ce,"category":ca,"priority":pr,
                                             "notes":task.get("notes", st.session_state.get("wa_src",""))})
                        st.divider()

                if selected:
                    if st.button(f"➕ Add {len(selected)} Task{'s' if len(selected)>1 else ''}",
                                 type="primary", key="wa_add_all", use_container_width=True):
                        added = 0
                        for task in selected:
                            if task["title"].strip():
                                t = {
                                    "ID": next_id(load_tasks()), "Centre": task["centre"],
                                    "Category": task["category"], "Title": task["title"].strip(),
                                    "Due Date": "", "Days Overdue": 0, "Status": "Pending",
                                    "Priority": task["priority"], "Owner": "Dr. Vaisakh V S",
                                    "Source": "WhatsApp", "Notes": task["notes"],
                                    "Reassigned To": "", "Email Message ID": "",
                                    "Date Added": date.today().isoformat(),
                                    "Last Updated": datetime.now().strftime("%Y-%m-%d %H:%M")
                                }
                                if save_task(t): added += 1
                        st.success(f"✅ Added {added} task{'s' if added>1 else ''}!")
                        st.session_state["wa_parsed"] = []
                        st.rerun()

        st.markdown("### ➕ Add New Task")
        with st.form("add", clear_on_submit=True):
            c1,c2 = st.columns(2)
            with c1:
                ft = st.text_area("Title *", height=80, placeholder="Describe clearly...")
                fc = st.selectbox("Centre *", CENTRES)
                fk = st.selectbox("Category", CATEGORIES)
                fs = st.selectbox("Source", SOURCES)
            with c2:
                fd = st.date_input("Due Date", value=None)
                fp = st.selectbox("Priority", PRIORITIES)
                fo = st.text_input("Owner", value="Dr. Vaisakh V S")
                fst= st.selectbox("Status", STATUSES[:3])
            fn = st.text_area("Notes / Context", height=90, placeholder="Email subject, meeting notes, tracker ref...")
            if st.form_submit_button("➕ Add Task", use_container_width=True, type="primary"):
                if not ft.strip() or not fc:
                    st.error("Title and Centre required.")
                else:
                    ov = max(0,(date.today()-fd).days) if fd else 0
                    t  = {"ID":next_id(df),"Centre":fc,"Category":fk,"Title":ft.strip(),"Due Date":str(fd) if fd else "","Days Overdue":ov,"Status":fst,"Priority":fp,"Owner":fo,"Source":fs,"Notes":fn,"Reassigned To":"","Email Message ID":"","Date Added":date.today().isoformat(),"Last Updated":datetime.now().strftime("%Y-%m-%d %H:%M")}
                    if save_task(t): st.success(f"✅ Task added to {fc}!"); st.rerun()

    with t5:
        st.markdown("### 📈 Analytics")
        if not df.empty:
            c1,c2 = st.columns(2)
            with c1:
                st.markdown("**Active by Centre**")
                st.bar_chart(df[~df["Status"].isin(["Done","Rejected"])].groupby("Centre").size().rename("Tasks"))
            with c2:
                st.markdown("**By Status**")
                st.bar_chart(df.groupby("Status").size().rename("Count"))
            st.markdown("**Active by Category**")
            st.bar_chart(df[~df["Status"].isin(["Done","Rejected"])].groupby("Category").size().rename("Tasks"))
            st.markdown("**Full Table**")
            st.dataframe(df, use_container_width=True, hide_index=True,
                column_config={"Title":st.column_config.TextColumn(width="large"),"Notes":st.column_config.TextColumn(width="medium"),"Days Overdue":st.column_config.NumberColumn(format="%d days")})
        else: st.info("No data yet.")

    with t6:
        st.markdown("### 🖥️ Server Monitor")
        col_ref, _ = st.columns([1,5])
        with col_ref:
            if st.button("🔄 Refresh", key="srv_refresh"):
                load_servers.clear()
                st.rerun()
        sdf = load_servers()
        if sdf.empty:
            st.info("No server data available. Check the ServerStatus sheet is accessible.")
        else:
            def color_status(val):
                v = str(val).strip().lower()
                if v == "success": return "background-color:#14532d;color:#86efac"
                if v == "failed":  return "background-color:#7f1d1d;color:#fca5a5"
                return ""
            sdf["Server Name"] = sdf["Server Name"].str.strip()
            for stype in SERVER_TYPE_ORDER:
                subset = sdf[sdf["Server Name"] == stype].copy()
                if subset.empty: continue
                for col in SERVER_DISPLAY_COLS:
                    if col not in subset.columns: subset[col] = ""
                st.markdown(f"**{stype}**")
                st.dataframe(
                    subset[SERVER_DISPLAY_COLS].style.map(color_status, subset=["Status"]),
                    use_container_width=True, hide_index=True
                )

    with t7:
        st.markdown("### 📅 Calendar")

        # ── Colour legend ─────────────────────────────────────────────────────
        st.markdown(
            '<div style="display:flex;gap:12px;flex-wrap:wrap;margin-bottom:8px;font-size:12px">'
            '<span style="background:#2563EB;color:#fff;padding:2px 10px;border-radius:20px">● Work Events</span>'
            '<span style="background:#059669;color:#fff;padding:2px 10px;border-radius:20px">● Holidays</span>'
            '<span style="background:#DC2626;color:#fff;padding:2px 10px;border-radius:20px">● Sundays</span>'
            '<span style="background:#F97316;color:#fff;padding:2px 10px;border-radius:20px">● Saturdays Off</span>'
            '<span style="background:#0891B2;color:#fff;padding:2px 10px;border-radius:20px">● Working Day Override</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── GCal task sync ────────────────────────────────────────────────────
        with st.expander("📤 Sync Pending Tasks → Google Calendar", expanded=False):
            st.caption(
                "Creates all-day events for every active task (Pending / Not Started / In Progress / On Hold). "
                "Previous sync events are removed first — no duplicates. "
                "Tasks appear on their Due Date (today if unset). "
                "Priority maps to colour: 🔴 High · 🟡 Medium · 🔵 Low."
            )
            st.info(
                f"**One-time setup:** Share `{MY_EMAIL}` with "
                "`taskflow-bot@taskflow-490709.iam.gserviceaccount.com` "
                "(Editor permission).",
                icon="ℹ️",
            )
            _sync_df   = load_tasks()
            _act_count = len(_sync_df[_sync_df["Status"].isin(_ACTIVE_STATUSES)]) if not _sync_df.empty else 0
            st.markdown(f"**Active tasks to sync:** {_act_count}")
            if st.button("📤 Sync Now", type="primary", key="gcal_sync_btn"):
                with st.spinner(f"Syncing {_act_count} tasks…"):
                    created, deleted, err = sync_tasks_to_gcal(_sync_df)
                if err:
                    st.error(f"Sync failed: {err}")
                else:
                    st.success(f"✅ {deleted} removed, {created} created.")
                    load_gcal_events.clear()
                    st.rerun()

        # ── Holiday management ────────────────────────────────────────────────
        btn_col, add_col, rem_col = st.columns([1, 3, 3])

        with btn_col:
            if st.button("🔄 Refresh", help="Force-reload the holiday sheet"):
                load_holidays.clear()
                st.rerun()

        with add_col:
            with st.expander("➕ Add Holiday", expanded=False):
                with st.form("add_holiday_form", clear_on_submit=True):
                    c1, c2    = st.columns([1, 2])
                    h_date    = c1.date_input("Date", value=date.today(), key="hol_date")
                    h_name    = c2.text_input("Holiday Name", placeholder="e.g. Diwali", key="hol_name")
                    h_reason  = st.text_input("Reason / Type", placeholder="e.g. National Holiday, Religious, State Holiday", key="hol_reason")
                    h_ctrs    = st.multiselect("Applies to", ["All"] + CENTRES, default=["All"], key="hol_ctrs")
                    if st.form_submit_button("💾 Save", use_container_width=True, type="primary"):
                        if not h_name.strip():
                            st.error("Name required.")
                        elif not h_ctrs:
                            st.error("Select at least one centre.")
                        else:
                            to_save = CENTRES if "All" in h_ctrs else h_ctrs
                            if save_holiday(h_date.strftime("%Y-%m-%d"), h_name.strip(), to_save, h_reason.strip()):
                                st.success(f"✅ Saved '{h_name.strip()}'.")
                                st.rerun()

        with rem_col:
            with st.expander("🗑️ Remove / Mark Working Day", expanded=False):
                _all_hols, _, _ = load_holidays()
                _named  = [h for h in _all_hols if h["name"] not in ("Sunday", "Working Day")]
                _dates  = sorted({h["date"] for h in _named})

                rm_tab, wd_tab = st.tabs(["🗑️ Remove Holiday", "🟢 Mark Working Day"])

                with rm_tab:
                    with st.form("rm_holiday_form", clear_on_submit=True):
                        rm_dt   = st.selectbox("Date", _dates or ["(none)"], key="rm_dt")
                        rm_opts = sorted({h["name"] for h in _named if h["date"] == rm_dt})
                        rm_nm   = st.selectbox("Holiday", rm_opts or ["(none)"], key="rm_nm")
                        rm_ctrs = sorted({h["centre"] for h in _named if h["date"] == rm_dt and h["name"] == rm_nm})
                        rm_sel  = st.multiselect(
                            "Remove for",
                            ["All"] + rm_ctrs,
                            default=["All"] if "All" in rm_ctrs else rm_ctrs,
                            key="rm_sel",
                        )
                        if st.form_submit_button("🗑️ Remove", use_container_width=True):
                            if not _dates or rm_nm == "(none)":
                                st.error("No holiday selected.")
                            elif not rm_sel:
                                st.error("Select at least one centre.")
                            else:
                                to_del = rm_ctrs if "All" in rm_sel else rm_sel
                                n = delete_holiday_rows(rm_dt, rm_nm, to_del)
                                if n > 0:
                                    st.success(f"✅ Removed {n} row(s).")
                                    st.rerun()
                                else:
                                    st.warning("No matching rows found.")

                with wd_tab:
                    with st.form("wd_form", clear_on_submit=True):
                        st.caption("Mark a Sunday or holiday as a working day.")
                        w1, w2  = st.columns([1, 2])
                        wd_dt   = w1.date_input("Date", value=date.today(), key="wd_dt")
                        wd_ctrs = w2.multiselect("Centres", CENTRES, key="wd_ctrs")
                        if st.form_submit_button("🟢 Mark Working Day", use_container_width=True, type="primary"):
                            if not wd_ctrs:
                                st.error("Select at least one centre.")
                            else:
                                if save_holiday(wd_dt.strftime("%Y-%m-%d"), "Working Day", wd_ctrs):
                                    st.success(f"✅ {wd_dt.strftime('%d %b %Y')} marked as working.")
                                    st.rerun()

        # ── Load data ─────────────────────────────────────────────────────────
        with st.spinner("Loading calendar…"):
            holidays, hol_errors, hol_raw = load_holidays()
            now_dt   = datetime.now()
            gcal_evs = load_gcal_events(now_dt.year, now_dt.month)

        # ── Filters ───────────────────────────────────────────────────────────
        named_hols  = [h for h in holidays if h["name"] not in ("Sunday", "Working Day")]
        hol_centres = sorted({
            h["centre"] for h in named_hols
            if h["centre"] not in ("All", "") and h["centre"] in CENTRES
        })
        fc1, fc2 = st.columns([3, 1])
        with fc1:
            sel_centres = st.multiselect(
                "Filter by centre", ["All"] + CENTRES,
                default=["All"], key="cal_ctr", placeholder="Select centres…",
            )
        with fc2:
            show_sundays = st.checkbox("Show Sundays", value=True, key="cal_sun")

        def _matches(centre):
            if not sel_centres or "All" in sel_centres:
                return True
            return centre in sel_centres or centre == "All"

        # ── Build event list ──────────────────────────────────────────────────
        hol_groups = {}   # (date, name) → {"centres": [...], "reason": "..."}
        for h in holidays:
            key = (h["date"], h["name"])
            if key not in hol_groups:
                hol_groups[key] = {"centres": [], "reason": h.get("reason", "")}
            hol_groups[key]["centres"].append(h["centre"])

        cal_events = []

        for (hdate, hname), info in hol_groups.items():
            centres        = list(dict.fromkeys(info["centres"]))
            reason         = info["reason"]
            is_sunday      = hname == "Sunday"
            is_saturday    = _is_saturday(hdate)
            is_working_day = hname == "Working Day"

            if is_sunday:
                if not show_sundays:
                    continue
            elif not any(_matches(c) for c in centres):
                continue

            disp = _display_centres(centres)

            if is_sunday:
                title, color, display = "Sunday", "#DC2626", "background"
            elif is_saturday and hname == "Holiday":
                title, color, display = "Saturday Off", "#F97316", "background"
            elif is_working_day:
                if "All" in disp:
                    label = "All Centres"
                elif len(disp) == 1:
                    label = disp[0]
                else:
                    label = ", ".join(disp[:3]) + (f" +{len(disp)-3}" if len(disp) > 3 else "")
                title, color, display = f"🟢 Working · {label}", "#0891B2", "block"
            else:
                if "All" in disp:
                    label = "All Centres"
                elif len(disp) == 1:
                    label = disp[0]
                elif len(disp) <= 3:
                    label = ", ".join(disp)
                else:
                    label = f"{', '.join(disp[:3])} +{len(disp)-3} more"
                title, color, display = f"🎉 {hname} · {label}", "#059669", "block"

            cal_events.append({
                "title":         title,
                "start":         hdate,
                "allDay":        True,
                "color":         color,
                "display":       display,
                "textColor":     "#fff",
                "extendedProps": {"centres": centres, "reason": reason},
            })

        for ev in gcal_evs:
            s_info = ev.get("start", {})
            e_info = ev.get("end",   {})
            start  = s_info.get("dateTime") or s_info.get("date", "")
            end    = e_info.get("dateTime") or e_info.get("date", "")
            if start:
                cal_events.append({
                    "title": ev.get("summary", "(No title)"),
                    "start": start,
                    "end":   end or start,
                    "color": "#2563EB",
                })

        # ── Render ────────────────────────────────────────────────────────────
        try:
            from streamlit_calendar import calendar as st_calendar
            cal_options = {
                "initialView":   "dayGridMonth",
                "initialDate":   now_dt.strftime("%Y-%m-%d"),
                "headerToolbar": {
                    "left":   "prev,next today",
                    "center": "title",
                    "right":  "dayGridMonth,listMonth",
                },
                "height":        650,
                "navLinks":      True,
                "dayMaxEvents":  True,
            }
            cal_state = st_calendar(events=cal_events, options=cal_options, key="main_calendar")
            if cal_state and cal_state.get("eventClick"):
                ev_info      = cal_state["eventClick"].get("event", {})
                ep           = ev_info.get("extendedProps", {})
                centres      = ep.get("centres", [])
                reason       = ep.get("reason", "")
                ctr_label    = f"  |  **Centres:** {', '.join(centres)}" if centres and centres != ["All"] else ""
                reason_label = f"  |  *{reason}*" if reason else ""
                st.info(f"**{ev_info.get('title','')}**  |  {ev_info.get('start','')[:10]}{ctr_label}{reason_label}")

        except ImportError:
            st.warning("Install `streamlit-calendar` for the visual calendar. Showing list view:")
            for ev in sorted(cal_events, key=lambda x: x["start"]):
                icon = "🎉" if ev.get("color") == "#059669" else "📌"
                st.markdown(f"{icon} **{ev['start'][:10]}** — {ev['title']}")

        # ── Diagnostics ───────────────────────────────────────────────────────
        _info_prefix    = "Anthropic API key not set"
        hol_warns       = [e for e in hol_errors if e.startswith(_info_prefix)]
        hol_real_errors = [e for e in hol_errors if not e.startswith(_info_prefix)]
        with st.expander("🔍 Holiday diagnostics", expanded=bool(hol_real_errors) or len(named_hols) == 0):
            st.markdown(f"**Holidays loaded:** {len(named_hols)}  |  **Centres:** {', '.join(hol_centres) or 'none'}")
            st.markdown(f"[Open Holiday Sheet](https://docs.google.com/spreadsheets/d/{HOLIDAY_SHEET_ID}/edit)")
            if hol_warns:
                st.info(hol_warns[0])
            if hol_real_errors:
                st.error("Errors:")
                for err in hol_real_errors:
                    st.code(err)
            elif not hol_warns:
                st.success("Holiday sheet loaded successfully (AI parser).")
            if named_hols:
                st.markdown("**First 10 parsed:**")
                st.json([{"date": h["date"], "name": h["name"], "centre": h["centre"]} for h in named_hols[:10]])
            if hol_raw:
                st.markdown("**Raw sheet (first 3000 chars):**")
                st.text(hol_raw[:3000])

        with st.expander("ℹ️ Setup notes", expanded=False):
            st.markdown(f"""
**Work Calendar:** Events load from `{MY_EMAIL}` via the service account.
Share your Google Calendar with `taskflow-bot@taskflow-490709.iam.gserviceaccount.com` (Editor for sync, Viewer for read-only).

**Holidays:** Loaded from the [Holiday Sheet](https://docs.google.com/spreadsheets/d/{HOLIDAY_SHEET_ID}/edit).
Any format is supported — Claude AI parses the sheet, with Python fallback if no API key is set.
""")

if __name__=="__main__": main()
# ── NATIVE STREAMLIT AUTO-REFRESH ─────────────────────────────
# This runs at the bottom of every script execution.
# Streamlit re-runs the entire script on each interaction,
# so the elapsed-time check in main() handles the 30s refresh.
# The st_autorefresh component below forces a rerun every 30s
# even when the user is idle (no interaction).
try:
    from streamlit_autorefresh import st_autorefresh
    st_autorefresh(interval=AUTO_REFRESH_SECONDS * 1000, key="autorefresh")
except ImportError:
    pass  # falls back to the session_state timer in main()

