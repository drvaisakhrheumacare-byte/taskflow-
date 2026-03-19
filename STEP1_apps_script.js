/**
 * ╔══════════════════════════════════════════════════════════════╗
 * ║         TaskFlow — Gmail Auto-Scanner & Task Manager        ║
 * ║         Account  : projects@rheumacare.com                  ║
 * ║         Sheet ID : 1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE ║
 * ╚══════════════════════════════════════════════════════════════╝
 *
 * HOW TO INSTALL:
 * 1. Open your TaskFlow Google Sheet
 * 2. Click Extensions → Apps Script
 * 3. Delete all existing code
 * 4. Paste this entire file
 * 5. Click Save (Ctrl+S)
 * 6. Click Run → scanNow (to test it works)
 * 7. Click Run → setupTriggers (to activate 30-min auto-scan)
 * 8. Authorize when prompted
 * Done — it runs automatically forever from this point on.
 */

// ── CONFIGURATION ─────────────────────────────────────────────
const MY_EMAIL      = "projects@rheumacare.com";
const NOTIFY_EMAIL  = "projects@rheumacare.com";
const SHEET_ID      = "1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE";
const SHEET_NAME    = "Master Tasks";
const SCAN_LABEL    = "TaskFlow/Processed";
const SCAN_INTERVAL = 30; // minutes

// ── CENTRES & KEYWORDS ────────────────────────────────────────
const CENTRE_KEYWORDS = {
  "Kumbalam"           : ["kumbalam","kbl","kumblan"],
  "Kollam"             : ["kollam","qlnla","qln","quilon"],
  "Guwahati"           : ["guwahati","guw","gauhati","gwt"],
  "Mysuru"             : ["mysuru","mysore","mys"],
  "Visakhapatnam"      : ["visakhapatnam","vizag","vsk","vsp","visakha"],
  "Bengaluru"          : ["bengaluru","bangalore","blr"],
  "Kochi"              : ["kochi","cochin","ernakulam","koc"],
  "Thiruvananthapuram" : ["thiruvananthapuram","trivandrum","tvm","thiruva"],
  "Kannur"             : ["kannur","cannanore","knn"],
  "Changanassery"      : ["changanassery","chengannur","cgs","changa"],
  "Bhubaneswar"        : ["bhubaneswar","bbsr","odisha","bhubaneswar"],
  "Ahmedabad"          : ["ahmedabad","ahd","gujarat","amd"],
};

const CATEGORY_KEYWORDS = {
  "IT / Systems"         : ["server","hms","impactin","qms","software","system","network","ip","backup","script","apps script","token display","database","it ","tech"],
  "Civil Work"           : ["civil","construction","partition","ceiling","flooring","plumbing","electrical","hvac","ac ","water","sewage","hoarding","layout","interior","furniture","welcraft","crescent","mep","contractor"],
  "Regulatory / Licence" : ["noc","licence","license","kseb","kwa","keil","electrical inspectorate","fire","elevator","registration","statutory","compliance","isos","permit"],
  "Finance"              : ["invoice","payment","bill","advance","amount","rs.","₹","gst","transfer","reimburse","salary","petty cash","expense"],
  "Legal / Contracts"    : ["agreement","lease","contract","work order","legal","advocate","deed","mou","wo "],
  "QMS / HMS"            : ["qms","queue","token","display","patient","appointment","nudging","touchpoint","workup","referral","ultrasound","usg","hms","impactin","dafy"],
  "HR / Admin"           : ["hr","employee","staff","joining","recruitment","training","induction","designation","salary"],
  "Operations"           : ["printer","barcode","cctv","pa system","ups","server","hardware","broadband","sip","fibre","procurement","purchase","order"],
};

const TASK_KEYWORDS = [
  "please","kindly","action required","follow up","followup",
  "do the needful","ensure","coordinate","pending from your end",
  "can you","could you","please check","please share","please confirm",
  "please do","please arrange","please review","please process",
  "please update","take action","following up","reminder","urgent",
  "please initiate","please proceed","request you","i need you",
  "we need you","vaisakh","vaishak","dr. vaisakh","dr vaisakh",
  "assigned to you","your task","action needed","please look into",
  "please handle","please coordinate","please ensure","need your help",
  "waiting for you","need you to","require your","your approval",
  "please approve","please verify","please confirm","please arrange",
];

const SKIP_SENDERS = [
  "noreply","no-reply","mailer","notification","notifications",
  "indigo","amazon","jio","doodle","makemytrip","booking.com",
  "agoda","qureos","wetransfer","themediaant","google.com",
  "linkedin","twitter","facebook","instagram","youtube",
  "flipkart","swiggy","zomato","uber","ola","paytm","phonepe",
  "hdfc","icici","sbi","axis","kotak","alerts@","info@","support@",
  "bsnl","airtel","jiomail","vodafone","billing@","invoice@",
];

const SHEET_COLS = [
  "ID","Centre","Category","Title","Due Date","Days Overdue",
  "Status","Priority","Owner","Source","Notes",
  "Reassigned To","Date Added","Last Updated","Email Message ID"
];

// ── SHEET HELPERS ─────────────────────────────────────────────
function getSheet() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let ws = ss.getSheetByName(SHEET_NAME);
  if (!ws) {
    ws = ss.insertSheet(SHEET_NAME);
    setupSheetHeader(ws);
  }
  return ws;
}

function setupSheetHeader(ws) {
  ws.getRange(1, 1, 1, SHEET_COLS.length).setValues([SHEET_COLS]);
  ws.getRange(1, 1, 1, SHEET_COLS.length)
    .setFontWeight("bold")
    .setBackground("#1C2030")
    .setFontColor("#E8EAFF")
    .setFontSize(11);
  ws.setFrozenRows(1);
  ws.setColumnWidth(3, 180);   // Category
  ws.setColumnWidth(4, 400);   // Title
  ws.setColumnWidth(11, 300);  // Notes
  Logger.log("✅ Sheet header created.");
}

function getNextId(ws) {
  const lastRow = ws.getLastRow();
  if (lastRow < 2) return 1;
  const ids = ws.getRange(2, 1, lastRow - 1, 1).getValues()
    .flat().map(v => parseInt(v)).filter(v => !isNaN(v));
  return ids.length > 0 ? Math.max(...ids) + 1 : 1;
}

function getProcessedMsgIds(ws) {
  const lastRow = ws.getLastRow();
  if (lastRow < 2) return new Set();
  const emailIdCol = SHEET_COLS.indexOf("Email Message ID") + 1;
  const ids = ws.getRange(2, emailIdCol, lastRow - 1, 1)
    .getValues().flat().filter(v => v !== "");
  return new Set(ids);
}

// ── EMAIL CLASSIFICATION ──────────────────────────────────────
function isTaskEmail(subject, body, from) {
  const fromLower = from.toLowerCase();
  if (SKIP_SENDERS.some(s => fromLower.includes(s))) return false;
  const text = (subject + " " + body).toLowerCase();
  return TASK_KEYWORDS.some(kw => text.includes(kw));
}

function detectCentre(subject, body) {
  const text = (subject + " " + body).toLowerCase();
  for (const [centre, keywords] of Object.entries(CENTRE_KEYWORDS)) {
    if (keywords.some(kw => text.includes(kw))) return centre;
  }
  return "General";
}

function detectCategory(subject, body) {
  const text = (subject + " " + body).toLowerCase();
  for (const [cat, keywords] of Object.entries(CATEGORY_KEYWORDS)) {
    if (keywords.some(kw => text.includes(kw))) return cat;
  }
  return "Operations";
}

function detectPriority(subject, body) {
  const text = (subject + " " + body).toLowerCase();
  const highWords = ["urgent","priority","critical","immediately","asap",
    "important","emergency","do this on priority","please do this"];
  return highWords.some(w => text.includes(w)) ? "High" : "";
}

// ── GMAIL LABEL ───────────────────────────────────────────────
function ensureLabel() {
  const parts = SCAN_LABEL.split("/");
  let path = "";
  parts.forEach(part => {
    path = path ? path + "/" + part : part;
    if (!GmailApp.getUserLabelByName(path)) GmailApp.createLabel(path);
  });
  return GmailApp.getUserLabelByName(SCAN_LABEL);
}

// ── FORMAT DATE ───────────────────────────────────────────────
function nowIST() {
  return Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd HH:mm");
}
function todayIST() {
  return Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd");
}

// ── MAIN SCAN FUNCTION ────────────────────────────────────────
function scanGmailForTasks() {
  Logger.log("🔍 Gmail scan started at " + nowIST());

  const ws = getSheet();
  const processedIds = getProcessedMsgIds(ws);
  const label = ensureLabel();
  const newTasks = [];

  // Search last 2 hours (overlapping window catches edge cases)
  const queries = [
    `to:${MY_EMAIL} newer_than:2h -label:${SCAN_LABEL.replace("/","-")}`,
    `cc:${MY_EMAIL} newer_than:2h -label:${SCAN_LABEL.replace("/","-")}`,
  ];

  queries.forEach(query => {
    try {
      const threads = GmailApp.search(query, 0, 100);
      threads.forEach(thread => {
        thread.getMessages().forEach(msg => {
          const msgId = msg.getId();
          if (processedIds.has(msgId)) return;

          const subject = msg.getSubject() || "(No Subject)";
          const from    = msg.getFrom() || "";
          const body    = msg.getPlainBody() || "";
          const date_   = msg.getDate();

          if (!isTaskEmail(subject, body, from)) {
            // Still label as processed so we don't recheck
            try { thread.addLabel(label); } catch(e) {}
            return;
          }

          const centre   = detectCentre(subject, body);
          const category = detectCategory(subject, body);
          const priority = detectPriority(subject, body);
          const snippet  = body.substring(0, 400).replace(/\n+/g, " ").trim();
          const taskId   = getNextId(ws);
          const dateStr  = Utilities.formatDate(date_, "Asia/Kolkata", "yyyy-MM-dd");

          const row = [
            taskId, centre, category,
            subject.substring(0, 200),
            "", 0,
            "Pending", priority,
            "Dr. Vaisakh V S", "Email",
            `From: ${from}\nDate: ${dateStr}\n\n${snippet}`,
            "", todayIST(), nowIST(), msgId
          ];

          ws.appendRow(row);
          processedIds.add(msgId);

          // Colour-code the row by status
          const newRow = ws.getLastRow();
          ws.getRange(newRow, 7).setBackground("#1a3a5c").setFontColor("#93C5FD"); // Status cell

          newTasks.push({ subject, from, centre, category, priority });
          Logger.log(`✅ Added: [${centre}] ${subject}`);

          try { thread.addLabel(label); } catch(e) {}
        });
      });
    } catch(e) {
      Logger.log("Query error: " + e.message);
    }
  });

  // Send notification if new tasks found
  if (newTasks.length > 0) {
    const lines = newTasks.map(t =>
      `• [${t.centre}] ${t.subject}\n  From: ${t.from}\n  Category: ${t.category}${t.priority ? " | ⭐ " + t.priority : ""}`
    ).join("\n\n");

    GmailApp.sendEmail(
      NOTIFY_EMAIL,
      `🔔 TaskFlow: ${newTasks.length} new task${newTasks.length > 1 ? "s" : ""} detected`,
      `Hi Vaisakh,\n\nTaskFlow detected ${newTasks.length} new task${newTasks.length > 1 ? "s" : ""} in your inbox:\n\n${lines}\n\nOpen your TaskFlow dashboard to review.\n\n— TaskFlow Auto-Scanner\n(scans every ${SCAN_INTERVAL} minutes)`
    );
  }

  Logger.log(`✅ Scan complete. New tasks: ${newTasks.length}`);
  return newTasks.length;
}

// ── DAILY SUMMARY ─────────────────────────────────────────────
function sendDailySummary() {
  const ws = getSheet();
  const data = ws.getDataRange().getValues();
  if (data.length < 2) return;

  const h = data[0];
  const rows = data.slice(1);

  const iStatus   = h.indexOf("Status");
  const iCentre   = h.indexOf("Centre");
  const iTitle    = h.indexOf("Title");
  const iOverdue  = h.indexOf("Days Overdue");
  const iPriority = h.indexOf("Priority");
  const iDue      = h.indexOf("Due Date");

  const active  = rows.filter(r => !["Done","Rejected"].includes(r[iStatus]));
  const overdue = active.filter(r => parseInt(r[iOverdue]) > 0)
                        .sort((a,b) => b[iOverdue] - a[iOverdue]);
  const highPri = active.filter(r => r[iPriority] === "High" && !(parseInt(r[iOverdue]) > 0));
  const rest    = active.filter(r => !overdue.includes(r) && !highPri.includes(r));

  const fmt = r => `• [${r[iCentre]}] ${String(r[iTitle]).substring(0,100)}${r[iDue] ? " (due " + r[iDue] + ")" : ""}`;

  let body = `Good morning Vaisakh! 🌅\n`;
  body += `TaskFlow Daily Summary — ${new Date().toDateString()}\n`;
  body += `${"─".repeat(50)}\n\n`;
  body += `📊 OVERVIEW\n`;
  body += `  Total active : ${active.length}\n`;
  body += `  🔴 Overdue   : ${overdue.length}\n`;
  body += `  ⭐ High pri  : ${highPri.length}\n`;
  body += `  🔵 Pending   : ${rest.length}\n\n`;

  if (overdue.length > 0) {
    body += `🔴 OVERDUE (${overdue.length})\n`;
    overdue.slice(0, 20).forEach(r => body += fmt(r) + ` — ${r[iOverdue]}d overdue\n`);
    body += "\n";
  }
  if (highPri.length > 0) {
    body += `⭐ HIGH PRIORITY (${highPri.length})\n`;
    highPri.slice(0, 10).forEach(r => body += fmt(r) + "\n");
    body += "\n";
  }
  if (rest.length > 0) {
    body += `🔵 OTHER PENDING (${rest.length})\n`;
    rest.slice(0, 15).forEach(r => body += fmt(r) + "\n");
    body += "\n";
  }

  body += `\nHave a productive day!\n— TaskFlow`;

  GmailApp.sendEmail(
    NOTIFY_EMAIL,
    `📋 TaskFlow Daily Summary — ${new Date().toDateString()}`,
    body
  );
  Logger.log("Daily summary sent.");
}

// ── UPDATE OVERDUE COUNTS (runs daily) ───────────────────────
function updateOverdueDays() {
  const ws = getSheet();
  const data = ws.getDataRange().getValues();
  if (data.length < 2) return;

  const h = data[0];
  const iDue     = h.indexOf("Due Date");
  const iOverdue = h.indexOf("Days Overdue");
  const iStatus  = h.indexOf("Status");
  const today    = new Date();
  today.setHours(0,0,0,0);

  for (let i = 1; i < data.length; i++) {
    const row    = data[i];
    const status = row[iStatus];
    if (["Done","Rejected"].includes(status)) continue;
    const due = row[iDue];
    if (!due) continue;
    const dueDate = new Date(due);
    if (isNaN(dueDate.getTime())) continue;
    dueDate.setHours(0,0,0,0);
    const diff = Math.floor((today - dueDate) / (1000*60*60*24));
    ws.getRange(i + 1, iOverdue + 1).setValue(Math.max(0, diff));
  }
  Logger.log("Overdue days updated.");
}

// ── SETUP TRIGGERS (run this ONCE manually) ───────────────────
function setupTriggers() {
  // Clear existing triggers
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));

  // Gmail scan every 30 minutes
  ScriptApp.newTrigger("scanGmailForTasks")
    .timeBased().everyMinutes(30).create();

  // Daily summary at 8 AM IST (2:30 AM UTC)
  ScriptApp.newTrigger("sendDailySummary")
    .timeBased().atHour(3).everyDays(1).create();

  // Update overdue counts daily at 6 AM IST
  ScriptApp.newTrigger("updateOverdueDays")
    .timeBased().atHour(1).everyDays(1).create();

  // Ensure sheet header exists
  getSheet();

  Logger.log("✅ All triggers set up successfully!");
  Logger.log("   • Gmail scan: every 30 minutes");
  Logger.log("   • Daily summary email: 8:00 AM IST");
  Logger.log("   • Overdue update: 6:00 AM IST");

  // Run initial scan immediately
  const count = scanGmailForTasks();
  Logger.log(`✅ Initial scan done. ${count} tasks found.`);
}

// ── MANUAL TRIGGERS ───────────────────────────────────────────
function scanNow()           { scanGmailForTasks(); }
function dailySummaryNow()   { sendDailySummary(); }
function updateOverdueNow()  { updateOverdueDays(); }
