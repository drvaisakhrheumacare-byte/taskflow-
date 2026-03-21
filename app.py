import streamlit as st
st.set_page_config(page_title="Growth Manager Dashboard", page_icon="📊", layout="wide")

import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime, date
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

CENTRES    = ["Nettoor","Kumbalam","Trivandrum","Bhubaneswar","Kannur","Changanassery","Guwahati","Kollam","Mysore","Bangalore","Ahmedabad","Others"]
CATEGORIES = ["Civil Work","Admin / Hardware","Regulatory / Licence","IT / Systems","QMS / HMS","Operations","Finance","HR / Admin","Legal / Contracts","Other"]
STATUSES   = ["Pending","Not Started","In Progress","On Hold","Done","Rejected","Reassigned"]
PRIORITIES = ["","High","Medium","Low"]
SOURCES    = ["Email","Tracker","Manual","Meeting","WhatsApp"]
SHEET_COLS = ["ID","Centre","Category","Title","Due Date","Days Overdue","Status","Priority","Owner","Source","Notes","Reassigned To","Date Added","Last Updated","Email Message ID"]
CENTRE_COLORS = {"Nettoor":"#6366F1","Kumbalam":"#7C3AED","Trivandrum":"#059669","Bhubaneswar":"#65A30D","Kannur":"#EA580C","Changanassery":"#0891B2","Guwahati":"#2563EB","Kollam":"#0D9488","Mysore":"#D97706","Bangalore":"#DB2777","Ahmedabad":"#F59E0B","Others":"#16A34A"}
STATUS_ICON = {"Pending":"🔵","Not Started":"⚪","In Progress":"🟡","On Hold":"🟠","Done":"✅","Rejected":"❌","Reassigned":"👤"}
SCOPES = ["https://spreadsheets.google.com/feeds","https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]

PING_SHEET_ID      = "1uf4pqKHEAbw6ny7CVZZVMw23PTfmv0QZzdCyj4fU33c"
PING_SERVERS_TAB   = "ServerStatus"
SERVER_TYPE_ORDER  = ["Main Server","Backup Server","Bitvoice Gateway","Bitvoice Server"]
SERVER_DISPLAY_COLS= ["Centre","Status","Timestamp","ResponseTime(ms)","Server IP","Last Online"]

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

def next_id(df):
    if df.empty: return 1
    ids = pd.to_numeric(df["ID"], errors="coerce").dropna()
    return int(ids.max())+1 if len(ids) else 1

def css():
    st.markdown("""<style>
    @import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@300;400;500;600&family=JetBrains+Mono:wght@700&display=swap');
    html,body,[class*="css"]{font-family:'DM Sans',sans-serif!important}
    [data-testid="stSidebar"]{background:#14172080;border-right:1px solid rgba(255,255,255,.06)}
    .block-container{padding-top:1.2rem!important}
    .tc{background:#1C2030;border:1px solid rgba(255,255,255,.07);border-radius:14px;padding:13px 17px;margin-bottom:9px;border-left:4px solid #2563EB}
    .tc.ov{border-left-color:#EF4444}.tc.hold{border-left-color:#F59E0B}.tc.reg{border-left-color:#8B5CF6}.tc.qms{border-left-color:#EC4899}.tc.done{opacity:.38;border-left-color:#4B5563}
    .ttl{font-size:14px;font-weight:500;color:#E8EAFF;line-height:1.4;margin-bottom:7px}
    .ttl.done{text-decoration:line-through;color:#6B7280}
    .tmeta{font-size:11px;color:#7880A4;display:flex;flex-wrap:wrap;gap:5px;align-items:center}
    .bdg{display:inline-block;font-size:10px;font-weight:700;padding:2px 8px;border-radius:20px;text-transform:uppercase;letter-spacing:.3px;white-space:nowrap}
    .ov_{background:rgba(239,68,68,.15);color:#F87171}.pd_{background:rgba(37,99,235,.15);color:#93C5FD}
    .hd_{background:rgba(245,158,11,.15);color:#FCD34D}.dn_{background:rgba(52,211,153,.15);color:#6EE7B7}
    .rj_{background:rgba(239,68,68,.1);color:#FCA5A5}.rg_{background:rgba(139,92,246,.15);color:#C4B5FD}
    .qm_{background:rgba(236,72,153,.15);color:#F9A8D4}.hi_{background:rgba(245,158,11,.12);color:#FCD34D}
    .em_{background:rgba(20,184,166,.15);color:#5EEAD4}.tr_{background:rgba(99,102,241,.15);color:#A5B4FC}
    .ct_{background:rgba(120,128,164,.15);color:#9CA3AF}
    .ch{font-size:11px;font-weight:700;text-transform:uppercase;letter-spacing:1px;color:#7880A4;padding:8px 0 6px;border-bottom:1px solid rgba(255,255,255,.05);margin:20px 0 10px}
    .mrow{display:flex;gap:10px;margin-bottom:16px;flex-wrap:wrap}
    .met{background:#1C2030;border:1px solid rgba(255,255,255,.07);border-radius:12px;padding:13px 18px;flex:1;min-width:90px;text-align:center}
    .mn{font-family:'JetBrains Mono',monospace;font-size:24px;font-weight:700}
    .ml{font-size:10px;color:#7880A4;text-transform:uppercase;letter-spacing:.5px;margin-top:3px}
    .stButton>button{border-radius:8px!important;font-size:12px!important;padding:3px 10px!important}
    </style>""", unsafe_allow_html=True)
    # Auto-refresh via Streamlit's built-in rerun after delay
    st.markdown(f"""<script>
    var tf_timer = setTimeout(function(){{
        var btns = window.parent.document.querySelectorAll('button');
        btns.forEach(function(b){{ if(b.innerText.includes('Refresh Now')) b.click(); }});
    }}, {AUTO_REFRESH_SECONDS * 1000});
    </script>""", unsafe_allow_html=True)

def task_card(row):
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
    is_done = status in ["Done","Rejected"]
    clr     = CENTRE_COLORS.get(centre,"#2563EB")

    cc = "tc"
    if is_done:               cc += " done"
    elif "Regulatory" in cat: cc += " reg"
    elif "QMS" in cat:        cc += " qms"
    elif status=="On Hold":   cc += " hold"
    elif overdue>0:           cc += " ov"

    if is_done:       sb = f'<span class="bdg dn_">{STATUS_ICON.get(status,"")} {status}</span>'
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
    tc = "ttl done" if is_done else "ttl"

    st.markdown(f"""<div class="{cc}" style="border-left-color:{clr}">
        <div class="{tc}">{title}</div>
        <div class="tmeta">{sb}{s2}{pb}{cb}{db}{ob}{rb}</div>
    </div>""", unsafe_allow_html=True)

    if not is_done:
        c1,c2,c3,c4,c5 = st.columns(5)
        if c1.button("✅ Done",   key=f"d_{tid}"): update_field(tid,"Status","Done");    st.rerun()
        if c2.button("⏸ Hold",   key=f"h_{tid}"): update_field(tid,"Status","On Hold"); st.rerun()
        if c3.button("❌ Reject", key=f"r_{tid}"): update_field(tid,"Status","Rejected");st.rerun()
        if c4.button("👤 Assign", key=f"a_{tid}"):
            st.session_state[f"rs_{tid}"] = not st.session_state.get(f"rs_{tid}",False)
        if c5.button("🗑 Delete", key=f"x_{tid}"): delete_row(tid); st.rerun()
        if st.session_state.get(f"rs_{tid}"):
            nm = st.text_input("Reassign to:", key=f"rn_{tid}", placeholder="Name / email")
            if st.button("Confirm →", key=f"rc_{tid}"):
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
        <div style="text-align:center;padding:50px 0 24px">
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
        st.markdown("## 📊 Growth Manager")
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
        st.caption(f"🔄 Next refresh in **{remaining}s**")
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

    st.markdown("# 📊 Growth Manager Dashboard")
    st.caption(f"Dr. Vaisakh VS · RheumaCARE · {datetime.now().strftime('%d %b %Y, %H:%M')}")

    if not df.empty:
        ov = len(df[(df["Days Overdue"]>0)&(~df["Status"].isin(["Done","Rejected"]))])
        pd_= len(df[df["Status"].isin(["Pending","Not Started","In Progress"])])
        hd = len(df[df["Status"]=="On Hold"])
        dn = len(df[df["Status"].isin(["Done","Rejected"])])
        ac = len(df[~df["Status"].isin(["Done","Rejected"])])
        st.markdown(f"""<div class="mrow">
          <div class="met"><div class="mn" style="color:#E8EAFF">{ac}</div><div class="ml">Active</div></div>
          <div class="met"><div class="mn" style="color:#F87171">{ov}</div><div class="ml">Overdue</div></div>
          <div class="met"><div class="mn" style="color:#93C5FD">{pd_}</div><div class="ml">Pending</div></div>
          <div class="met"><div class="mn" style="color:#FCD34D">{hd}</div><div class="ml">On Hold</div></div>
          <div class="met"><div class="mn" style="color:#6EE7B7">{dn}</div><div class="ml">Done</div></div>
        </div>""", unsafe_allow_html=True)

    st.divider()
    t1,t2,t3,t4,t5,t6 = st.tabs(["📋 All Tasks","🔴 Overdue","📊 By Centre","➕ Add Task","📈 Analytics","🖥️ Server Monitor"])

    with t1:
        if filt.empty:
            st.info("No tasks found. Load tasks or let the Gmail scanner populate automatically.")
        else:
            for centre in CENTRES:
                cdf = filt[filt["Centre"]==centre]
                if cdf.empty: continue
                act = cdf[~cdf["Status"].isin(["Done","Rejected"])]
                clr = CENTRE_COLORS.get(centre,"#2563EB")
                st.markdown(f'<div class="ch" style="color:{clr}">🏥 {centre.upper()} · {len(act)} active</div>', unsafe_allow_html=True)
                for _,row in cdf.sort_values(["Days Overdue","Priority"],ascending=[False,True]).iterrows():
                    task_card(row)

    with t2:
        odf = filt[(filt["Days Overdue"]>0)&(~filt["Status"].isin(["Done","Rejected"]))].sort_values("Days Overdue",ascending=False)
        if odf.empty: st.success("🎉 No overdue tasks!")
        else:
            st.error(f"⚠️ {len(odf)} overdue — most critical first")
            for _,row in odf.iterrows(): task_card(row)

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
                for _,row in pdf.sort_values("Days Overdue",ascending=False).iterrows(): task_card(row)
            else: st.info(f"No tasks for {pick}.")

    with t4:
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
                    subset[SERVER_DISPLAY_COLS].style.applymap(color_status, subset=["Status"]),
                    use_container_width=True, hide_index=True
                )

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

