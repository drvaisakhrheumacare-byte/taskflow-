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
SHEET_COLS = ["ID","Centre","Category","Title","Due Date","Days Overdue","Status","Priority","Owner","Source","Notes","Reassigned To","Date Added","Last Updated","Email Message ID"]
CENTRE_COLORS = {"Nettoor":"#6366F1","Kumbalam":"#7C3AED","Trivandrum":"#059669","Bhubaneswar":"#65A30D","Kannur":"#EA580C","Changanassery":"#0891B2","Guwahati":"#2563EB","Kollam":"#0D9488","Mysore":"#D97706","Bangalore":"#DB2777","Ahmedabad":"#F59E0B","Visakhapatnam":"#DC2626","Others":"#16A34A"}
STATUS_ICON = {"Pending":"🔵","Not Started":"⚪","In Progress":"🟡","On Hold":"🟠","Done":"✅","Rejected":"❌","Reassigned":"👤","Not Mine":"🚫"}
SCOPES = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]

PING_SHEET_ID      = "1uf4pqKHEAbw6ny7CVZZVMw23PTfmv0QZzdCyj4fU33c"
PING_SERVERS_TAB   = "ServerStatus"
SERVER_TYPE_ORDER  = ["Main Server","Backup Server","Bitvoice Gateway","Bitvoice Server"]
SERVER_DISPLAY_COLS= ["Centre","Status","Timestamp","ResponseTime(ms)","Server IP","Last Online"]

HOLIDAY_SHEET_ID   = "1dn9uXm0sY8hUgkZ01uf5YDazkbp0S2IP8-beg2C7krY"
GCAL_SCOPES        = ["https://www.googleapis.com/auth/calendar.readonly"]

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

@st.cache_data(ttl=3600)
def load_holidays():
    """Load holidays from sheet (via Claude AI to handle irregular formats) + auto-add all Sundays."""
    import anthropic, json

    events = []

    # ── 1. All Sundays for current + next year are holidays for all centres ──
    for yr in [datetime.now().year, datetime.now().year + 1]:
        d = date(yr, 1, 1)
        while d.year == yr:
            if d.weekday() == 6:  # Sunday
                events.append({"date": d.strftime("%Y-%m-%d"), "name": "Sunday", "centre": "All"})
            d += timedelta(days=1)

    # ── 2. Load sheet data and parse with Claude ──────────────────────────────
    gs_client = get_client()
    if not gs_client:
        return events
    try:
        sh = gs_client.open_by_key(HOLIDAY_SHEET_ID)
        try:
            ai = anthropic.Anthropic(api_key=st.secrets["anthropic"]["api_key"])
        except Exception:
            return events

        current_year = datetime.now().year
        for ws in sh.worksheets():
            try:
                raw_rows = ws.get_all_values()
                if not raw_rows:
                    continue
                tab_name = ws.title
                raw_text = "\n".join(["\t".join(row) for row in raw_rows])

                resp = ai.messages.create(
                    model="claude-haiku-4-5-20251001",
                    max_tokens=2048,
                    messages=[{"role": "user", "content": f"""Extract all holidays/events from this Google Sheet data.
Return ONLY a valid JSON array — no explanation, no markdown fences.
Each item: {{"date": "YYYY-MM-DD", "name": "Holiday name", "centre": "Centre name or All"}}

Rules:
- Convert all date formats to YYYY-MM-DD
- If year is missing, assume {current_year}
- If the sheet covers all centres or no specific centre, set centre to "All"
- If the tab name looks like a centre name, use it as the centre
- Tab name: "{tab_name}"

Sheet data:
{raw_text}"""}]
                )

                raw_json = resp.content[0].text.strip()
                # Strip markdown code fences if present
                if raw_json.startswith("```"):
                    raw_json = raw_json.split("```")[1]
                    if raw_json.startswith("json"):
                        raw_json = raw_json[4:]
                parsed = json.loads(raw_json)
                if isinstance(parsed, list):
                    for item in parsed:
                        if item.get("date") and item.get("name"):
                            events.append({
                                "date":   item["date"],
                                "name":   item["name"],
                                "centre": item.get("centre", tab_name),
                            })
            except Exception:
                continue
    except Exception as e:
        st.warning(f"Could not load holidays: {e}")

    return events

@st.cache_data(ttl=300)
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

def save_task(task):
    ws = get_ws()
    if not ws: return False
    try:
        ws.append_row([task.get(c,"") for c in SHEET_COLS], value_input_option="USER_ENTERED")
        load_tasks.clear(); return True
    except Exception as e:
        st.error(f"Save failed: {e}"); return False

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

@st.cache_resource
def get_anthropic_client():
    try:
        import anthropic
        return anthropic.Anthropic(api_key=st.secrets["ANTHROPIC_API_KEY"])
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

def task_card(row, pfx=""):
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
    is_done    = status in ["Done","Rejected"]
    is_notmine = status == "Not Mine"
    clr     = CENTRE_COLORS.get(centre,"#2563EB")

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
    pb = '<span class="bdg hi_">★ High</span>'       if pri=="High" else ""
    cb = f'<span class="bdg ct_">{cat}</span>'        if cat else ""
    db = f'<span>📅 {due}</span>'                     if due else ""
    ob = f'<span>👤 {owner}</span>'                   if owner and owner!="Dr. Vaisakh V S" else ""
    rb = f'<span>↪ {reassign}</span>'                 if reassign else ""
    tc = "ttl done" if (is_done or is_notmine) else "ttl"

    st.markdown(f"""<div class="{cc}" style="border-left-color:{clr}">
        <div class="{tc}">{title}</div>
        <div class="tmeta">{sb}{s2}{pb}{cb}{db}{ob}{rb}</div>
    </div>""", unsafe_allow_html=True)

    if is_notmine:
        c1,c2 = st.columns([1,5])
        if c1.button("↩ Reactivate", key=f"rm_{pfx}{tid}"): update_field(tid,"Status","Pending"); st.rerun()
        if notes:
            with st.expander("📝 Notes"): st.caption(notes)
    elif not is_done:
        c1,c2,c3 = st.columns(3)
        if c1.button("✅ Done",   key=f"d_{pfx}{tid}"): update_field(tid,"Status","Done");     st.rerun()
        if c2.button("⏸ Hold",   key=f"h_{pfx}{tid}"): update_field(tid,"Status","On Hold");  st.rerun()
        if c3.button("❌ Reject", key=f"r_{pfx}{tid}"): update_field(tid,"Status","Rejected"); st.rerun()
        c4,c5,c6 = st.columns(3)
        if c4.button("🚫 Not Mine", key=f"nm_{pfx}{tid}"): update_field(tid,"Status","Not Mine"); st.rerun()
        if c5.button("👤 Assign",   key=f"a_{pfx}{tid}"):
            st.session_state[f"rs_{pfx}{tid}"] = not st.session_state.get(f"rs_{pfx}{tid}",False)
        if c6.button("🗑 Delete",   key=f"x_{pfx}{tid}"): delete_row(tid); st.rerun()
        if st.session_state.get(f"rs_{pfx}{tid}"):
            nm = st.text_input("Reassign to:", key=f"rn_{pfx}{tid}", placeholder="Name / email")
            if st.button("Confirm →", key=f"rc_{pfx}{tid}"):
                update_field(tid,"Status","Reassigned"); update_field(tid,"Reassigned To",nm)
                st.session_state[f"rs_{tid}"] = False; st.rerun()
        if notes:
            with st.expander("📝 Notes"): st.caption(notes)
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

    with t1:
        active = filt[~filt["Status"].isin(["Done","Rejected","On Hold","Not Mine"])]
        if active.empty:
            st.success("🎉 No active tasks!")
        else:
            for centre in CENTRES:
                cdf = active[active["Centre"]==centre]
                if cdf.empty: continue
                clr = CENTRE_COLORS.get(centre,"#2563EB")
                st.markdown(f'<div class="ch" style="color:{clr}">🏥 {centre.upper()} · {len(cdf)} active</div>', unsafe_allow_html=True)
                for _,row in cdf.sort_values(["Days Overdue","Priority"],ascending=[False,True]).iterrows():
                    task_card(row, pfx="t1_")

    with t2:
        odf = filt[(filt["Days Overdue"]>0)&(~filt["Status"].isin(["Done","Rejected"]))].sort_values("Days Overdue",ascending=False)
        if odf.empty: st.success("🎉 No overdue tasks!")
        else:
            st.error(f"⚠️ {len(odf)} overdue — most critical first")
            for _,row in odf.iterrows(): task_card(row, pfx="t2_")

    with t3:
        smry = []
        for c in CENTRES:
            cdf = df[df["Centre"]==c]
            if cdf.empty: continue
            smry.append({"Centre":c,"Active":len(cdf[~cdf["Status"].isin(["Done","Rejected"])]),"Overdue":len(cdf[(cdf["Days Overdue"]>0)&(~cdf["Status"].isin(["Done","Rejected"]))]),"Pending":len(cdf[cdf["Status"].isin(["Pending","Not Started"])]),"Hold":len(cdf[cdf["Status"]=="On Hold"]),"Done":len(cdf[cdf["Status"].isin(["Done","Rejected"])]),"Total":len(cdf)})
        if smry:
            st.dataframe(pd.DataFrame(smry), use_container_width=True, hide_index=True)
            st.divider()
            pick = st.selectbox("Drill into centre:", CENTRES)
            pdf  = filt[filt["Centre"]==pick]
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

        # ── Colour legend ─────────────────────────────────────
        st.markdown(
            '<div style="display:flex;gap:16px;margin-bottom:8px;font-size:12px">'
            '<span style="background:#2563EB;color:#fff;padding:2px 10px;border-radius:20px">● Work Events</span>'
            '<span style="background:#059669;color:#fff;padding:2px 10px;border-radius:20px">● Holidays</span>'
            '<span style="background:#DC2626;color:#fff;padding:2px 10px;border-radius:20px">● Sundays</span>'
            '</div>',
            unsafe_allow_html=True,
        )

        # ── Load data ─────────────────────────────────────────
        with st.spinner("Loading calendar…"):
            holidays   = load_holidays()
            now_dt     = datetime.now()
            gcal_evs   = load_gcal_events(now_dt.year, now_dt.month)

        # ── Build event list for streamlit-calendar ────────────
        cal_events = []

        for h in holidays:
            is_sunday = h["name"] == "Sunday"
            centre_label = f" · {h['centre']}" if h["centre"] not in ("All", "") and not is_sunday else ""
            cal_events.append({
                "title":           "🔴 Sunday" if is_sunday else f"🎉 {h['name']}{centre_label}",
                "start":           h["date"],
                "allDay":          True,
                "color":           "#DC2626" if is_sunday else "#059669",
                "display":         "background" if is_sunday else "block",
                "textColor":       "#fff",
            })

        for ev in gcal_evs:
            s_info = ev.get("start", {})
            e_info = ev.get("end",   {})
            start  = s_info.get("dateTime") or s_info.get("date", "")
            end    = e_info.get("dateTime") or e_info.get("date", "")
            if not start:
                continue
            cal_events.append({
                "title": ev.get("summary", "(No title)"),
                "start": start,
                "end":   end or start,
                "color": "#2563EB",
            })

        # ── Render calendar ───────────────────────────────────
        try:
            from streamlit_calendar import calendar as st_calendar
            cal_options = {
                "initialView":    "dayGridMonth",
                "initialDate":    now_dt.strftime("%Y-%m-%d"),
                "headerToolbar":  {
                    "left":   "prev,next today",
                    "center": "title",
                    "right":  "dayGridMonth,listMonth",
                },
                "height":         650,
                "navLinks":       True,
                "dayMaxEvents":   True,
                "eventDisplay":   "block",
            }
            cal_state = st_calendar(events=cal_events, options=cal_options, key="main_calendar")

            # Show clicked event detail
            if cal_state and cal_state.get("eventClick"):
                ev_info = cal_state["eventClick"].get("event", {})
                st.info(f"**{ev_info.get('title','')}**  |  {ev_info.get('start','')[:10]}")

        except ImportError:
            # Fallback list view if package not installed yet
            st.warning("Install `streamlit-calendar` to see the visual calendar. Showing list view:")
            merged = sorted(cal_events, key=lambda x: x["start"])
            if not merged:
                st.info("No events found.")
            for ev in merged:
                icon = "🎉" if ev.get("color") == "#059669" else "📌"
                st.markdown(f"{icon} **{ev['start'][:10]}** — {ev['title']}")

        # ── Quick legend / instructions ───────────────────────
        with st.expander("ℹ️ Setup notes", expanded=False):
            st.markdown(f"""
**Work Calendar:** Events load from `{MY_EMAIL}` via the service account.
To enable this, share your Google Calendar with the service account:
> `taskflow-bot@taskflow-490709.iam.gserviceaccount.com` (Viewer access)

**Holidays:** Loaded from the [Holiday Sheet](https://docs.google.com/spreadsheets/d/{HOLIDAY_SHEET_ID}/edit).
Each worksheet tab should have columns named `Date`, `Event/Holiday`, and optionally `Centre`.
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

