"""
Daily Task Digest — sends a formatted HTML email every morning.
Run via GitHub Actions; secrets injected as environment variables.
"""

import os
import json
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta

import gspread
from google.oauth2.service_account import Credentials

# ── Config ────────────────────────────────────────────────────
SHEET_ID  = os.environ["SHEET_ID"]
SHEET_TAB = "Master Tasks"
SCOPES    = ["https://spreadsheets.google.com/feeds",
             "https://www.googleapis.com/auth/spreadsheets",
             "https://www.googleapis.com/auth/drive"]

PENDING_STATUSES = {"Pending", "Not Started", "In Progress", "On Hold", "Reassigned"}

IST = timezone(timedelta(hours=5, minutes=30))

PRIORITY_ORDER = {"High": 0, "Medium": 1, "Low": 2, "": 3}
PRIORITY_COLOR = {"High": "#DC2626", "Medium": "#D97706", "Low": "#16A34A", "": "#6B7280"}

STATUS_ICON = {
    "Pending": "🔵", "Not Started": "⚪", "In Progress": "🟡",
    "On Hold": "🟠", "Reassigned": "👤",
}

# ── Google Sheets ─────────────────────────────────────────────
def load_tasks():
    creds_json = os.environ["GCP_SERVICE_ACCOUNT_JSON"]
    creds_info = json.loads(creds_json)
    creds = Credentials.from_service_account_info(creds_info, scopes=SCOPES)
    client = gspread.authorize(creds)
    ws = client.open_by_key(SHEET_ID).worksheet(SHEET_TAB)
    rows = ws.get_all_records()
    return rows

# ── Filter & sort ─────────────────────────────────────────────
def get_pending(rows):
    today = datetime.now(IST).date()
    tasks = []
    for r in rows:
        if r.get("Status", "") not in PENDING_STATUSES:
            continue
        due_raw = r.get("Due Date", "")
        try:
            due = datetime.strptime(str(due_raw).strip(), "%Y-%m-%d").date()
            days_left = (due - today).days
        except Exception:
            due = None
            days_left = None
        tasks.append({**r, "_due": due, "_days_left": days_left})

    # sort: overdue first, then by due date, then no-due-date
    def sort_key(t):
        if t["_days_left"] is None:
            return (1, 9999)
        return (0, t["_days_left"])

    tasks.sort(key=sort_key)
    return tasks

# ── HTML builder ──────────────────────────────────────────────
def due_label(days_left):
    if days_left is None:
        return '<span style="color:#6B7280">No due date</span>'
    if days_left < 0:
        return f'<span style="color:#DC2626;font-weight:bold">⚠ {abs(days_left)}d overdue</span>'
    if days_left == 0:
        return '<span style="color:#D97706;font-weight:bold">Due TODAY</span>'
    if days_left <= 3:
        return f'<span style="color:#D97706">Due in {days_left}d</span>'
    return f'<span style="color:#16A34A">Due in {days_left}d</span>'

def build_html(tasks, generated_at):
    by_centre = {}
    for t in tasks:
        centre = t.get("Centre", "Unknown") or "Unknown"
        by_centre.setdefault(centre, []).append(t)

    total = len(tasks)
    overdue = sum(1 for t in tasks if t["_days_left"] is not None and t["_days_left"] < 0)
    due_today = sum(1 for t in tasks if t["_days_left"] == 0)

    rows_html = ""
    for centre in sorted(by_centre.keys()):
        ctasks = by_centre[centre]
        ctasks.sort(key=lambda t: (
            PRIORITY_ORDER.get(t.get("Priority", ""), 3),
            t["_days_left"] if t["_days_left"] is not None else 9999
        ))
        rows_html += f"""
        <tr>
          <td colspan="5" style="background:#1E3A5F;color:#fff;font-weight:bold;
              padding:8px 12px;font-size:13px;letter-spacing:0.5px;">
            📍 {centre} &nbsp;·&nbsp; {len(ctasks)} task{'s' if len(ctasks)!=1 else ''}
          </td>
        </tr>"""
        for i, t in enumerate(ctasks):
            bg = "#F9FAFB" if i % 2 == 0 else "#FFFFFF"
            prio = t.get("Priority", "") or ""
            pcolor = PRIORITY_COLOR.get(prio, "#6B7280")
            status = t.get("Status", "")
            icon = STATUS_ICON.get(status, "")
            title = t.get("Title", t.get("Task", "—"))
            notes = t.get("Notes", "") or ""
            reassigned = t.get("Reassigned To", "") or ""
            extra = ""
            if reassigned:
                extra = f'<br><span style="font-size:11px;color:#7C3AED">→ Reassigned to: {reassigned}</span>'
            if notes:
                extra += f'<br><span style="font-size:11px;color:#6B7280">{notes[:120]}{"…" if len(notes)>120 else ""}</span>'

            rows_html += f"""
        <tr style="background:{bg}">
          <td style="padding:8px 12px;font-size:13px;max-width:320px">
            {title}{extra}
          </td>
          <td style="padding:8px 12px;font-size:12px;color:#374151">{t.get('Category','')}</td>
          <td style="padding:8px 12px;font-size:12px;font-weight:bold;color:{pcolor}">{prio or '—'}</td>
          <td style="padding:8px 12px;font-size:12px">{icon} {status}</td>
          <td style="padding:8px 12px;font-size:12px">{due_label(t['_days_left'])}</td>
        </tr>"""

    html = f"""<!DOCTYPE html>
<html>
<head><meta charset="utf-8">
<style>
  body {{ font-family: 'Segoe UI', Arial, sans-serif; margin: 0; padding: 20px; background: #F3F4F6; }}
  .container {{ max-width: 860px; margin: auto; background: #fff; border-radius: 8px;
                box-shadow: 0 2px 8px rgba(0,0,0,0.08); overflow: hidden; }}
  .header {{ background: #1E3A5F; color: #fff; padding: 24px 32px; }}
  .header h1 {{ margin: 0; font-size: 22px; }}
  .header p  {{ margin: 4px 0 0; font-size: 13px; opacity: 0.8; }}
  .stats {{ display: flex; gap: 16px; padding: 20px 32px; background: #EFF6FF; }}
  .stat {{ background: #fff; border-radius: 6px; padding: 12px 20px; text-align: center;
           border-top: 3px solid #1E3A5F; flex: 1; }}
  .stat .num {{ font-size: 28px; font-weight: bold; color: #1E3A5F; }}
  .stat .lbl {{ font-size: 11px; color: #6B7280; text-transform: uppercase; letter-spacing: 0.5px; }}
  .table-wrap {{ padding: 20px 32px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  th {{ background: #374151; color: #fff; padding: 10px 12px; text-align: left; font-size: 12px; }}
  .footer {{ padding: 16px 32px; font-size: 11px; color: #9CA3AF; border-top: 1px solid #E5E7EB; }}
</style>
</head>
<body>
<div class="container">
  <div class="header">
    <h1>📋 RheumaCARE — Daily Task Digest</h1>
    <p>Generated {generated_at} IST &nbsp;·&nbsp; Growth Manager Dashboard</p>
  </div>
  <div class="stats">
    <div class="stat"><div class="num">{total}</div><div class="lbl">Total Pending</div></div>
    <div class="stat"><div class="num" style="color:#DC2626">{overdue}</div><div class="lbl">Overdue</div></div>
    <div class="stat"><div class="num" style="color:#D97706">{due_today}</div><div class="lbl">Due Today</div></div>
    <div class="stat"><div class="num">{len(by_centre)}</div><div class="lbl">Centres Active</div></div>
  </div>
  <div class="table-wrap">
    <table>
      <thead>
        <tr>
          <th>Task</th><th>Category</th><th>Priority</th><th>Status</th><th>Due</th>
        </tr>
      </thead>
      <tbody>
        {rows_html}
      </tbody>
    </table>
  </div>
  <div class="footer">
    This digest is auto-generated every morning at 8:00 AM IST. Print to PDF for daily follow-up.
  </div>
</div>
</body>
</html>"""
    return html

# ── Send email ────────────────────────────────────────────────
def send_email(html, subject, sender, password, recipient):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = recipient
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as s:
        s.login(sender, password)
        s.sendmail(sender, recipient, msg.as_string())

# ── Main ──────────────────────────────────────────────────────
def main():
    now_ist = datetime.now(IST)
    generated_at = now_ist.strftime("%d %b %Y, %I:%M %p")
    date_str     = now_ist.strftime("%d %b %Y")

    print("Loading tasks from Google Sheets…")
    rows  = load_tasks()
    tasks = get_pending(rows)
    print(f"Found {len(tasks)} pending tasks.")

    html = build_html(tasks, generated_at)

    sender    = os.environ["SENDER_EMAIL"]
    password  = os.environ["GMAIL_APP_PASSWORD"]
    recipient = os.environ["RECIPIENT_EMAIL"]
    subject   = f"📋 RheumaCARE Daily Digest — {date_str} ({len(tasks)} pending)"

    print(f"Sending digest to {recipient}…")
    send_email(html, subject, sender, password, recipient)
    print("Done.")

if __name__ == "__main__":
    main()
