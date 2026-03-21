/**
 * TaskFlow — Google Apps Script Backend
 * ═══════════════════════════════════════════════════════════════
 * SETUP:
 * 1. Open your Google Sheet → Extensions → Apps Script
 * 2. Paste this entire file into the editor
 * 3. Run setupTriggers() ONCE manually (Run menu → Run function)
 * 4. Authorize when prompted
 *
 * This script:
 * - Scans Gmail every 30 minutes for task-related emails
 * - Adds new tasks to the "Master Tasks" sheet automatically
 * - Sends you a daily summary email at 8 AM
 * - Marks emails as processed so they aren't added twice
 * ═══════════════════════════════════════════════════════════════
 */

const SHEET_NAME   = "Master Tasks";
const MY_EMAIL     = "projects@rheumacare.com";
const NOTIFY_EMAIL = "projects@rheumacare.com";  // where to send alerts
const LABEL_NAME   = "TaskFlow/Processed";       // Gmail label for scanned emails

const CENTRES = [
  "Nettoor","Kumbalam","Trivandrum","Bhubaneswar",
  "Kannur","Changanassery","Guwahati","Kollam",
  "Mysore","Bangalore","Ahmedabad","Others"
];

const CENTRE_KEYWORDS = {
  "Nettoor":       ["nettoor","nettur"],
  "Kumbalam":      ["kumbalam","kbl"],
  "Trivandrum":    ["trivandrum","thiruvananthapuram","tvm"],
  "Bhubaneswar":   ["bhubaneswar","bbsr","bhubaneshwar","odisha"],
  "Kannur":        ["kannur","cannanore","knn"],
  "Changanassery": ["changanassery","chengannur","cgs"],
  "Guwahati":      ["guwahati","guw","gauhati"],
  "Kollam":        ["kollam","qln","quilon"],
  "Mysore":        ["mysore","mysuru","mys"],
  "Bangalore":     ["bangalore","bengaluru","blr"],
  "Ahmedabad":     ["ahmedabad","ahd","gujarat"],
};

const TASK_KEYWORDS = [
  "please","kindly","action required","follow up","followup",
  "assigned to you","your task","do the needful","ensure",
  "coordinate","pending from your end","can you","could you",
  "please check","please share","please confirm","please do",
  "please arrange","please review","please process","please update",
  "take action","following up","reminder","urgent","please initiate",
  "please proceed","request you","i need you","we need you",
  "vaisakh","vaishak","@dr. vaisakh","dr vaisakh"
];

const SHEET_COLS = [
  "ID","Centre","Category","Title","Due Date","Days Overdue",
  "Status","Priority","Owner","Source","Notes","Reassigned To",
  "Date Added","Last Updated","Email Message ID"
];

// ── SETUP: Run this once manually ───────────────────────────
function setupTriggers() {
  // Delete existing triggers
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));

  // Scan Gmail every 30 minutes
  ScriptApp.newTrigger("scanGmailForTasks")
    .timeBased()
    .everyMinutes(30)
    .create();

  // Daily summary at 8 AM IST (UTC+5:30 = 2:30 AM UTC)
  ScriptApp.newTrigger("sendDailySummary")
    .timeBased()
    .atHour(3)  // 8:30 AM IST approx
    .everyDays(1)
    .create();

  Logger.log("✅ Triggers set up: Gmail scan every 30 min, daily summary at 8 AM");
  ensureSheetHeader();
  ensureGmailLabel();
}

// ── ENSURE SHEET HAS HEADER ──────────────────────────────────
function ensureSheetHeader() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  let ws = ss.getSheetByName(SHEET_NAME);
  if (!ws) {
    ws = ss.insertSheet(SHEET_NAME);
  }
  const firstRow = ws.getRange(1, 1, 1, SHEET_COLS.length).getValues()[0];
  if (firstRow[0] !== "ID") {
    ws.getRange(1, 1, 1, SHEET_COLS.length).setValues([SHEET_COLS]);
    ws.getRange(1, 1, 1, SHEET_COLS.length).setFontWeight("bold");
    ws.setFrozenRows(1);
    // Format header row
    ws.getRange(1, 1, 1, SHEET_COLS.length)
      .setBackground("#1C2030")
      .setFontColor("#E8EAFF");
    Logger.log("Header row created.");
  }
}

// ── ENSURE GMAIL LABEL EXISTS ────────────────────────────────
function ensureGmailLabel() {
  const parts = LABEL_NAME.split("/");
  let parent = null;
  let labelPath = "";
  parts.forEach(part => {
    labelPath = labelPath ? labelPath + "/" + part : part;
    let existing = GmailApp.getUserLabelByName(labelPath);
    if (!existing) {
      if (parent) {
        // sub-label
        GmailApp.createLabel(labelPath);
      } else {
        GmailApp.createLabel(labelPath);
      }
    }
    parent = labelPath;
  });
}

// ── DETECT IF EMAIL IS TASK-RELATED ─────────────────────────
function isTaskEmail(subject, body) {
  const text = (subject + " " + body).toLowerCase();
  return TASK_KEYWORDS.some(kw => text.includes(kw));
}

// ── DETECT CENTRE FROM EMAIL ─────────────────────────────────
function detectCentre(subject, body) {
  const text = (subject + " " + body).toLowerCase();
  for (const [centre, keywords] of Object.entries(CENTRE_KEYWORDS)) {
    if (keywords.some(kw => text.includes(kw))) return centre;
  }
  return "General";
}

// ── GET NEXT ROW ID ──────────────────────────────────────────
function getNextId(ws) {
  const lastRow = ws.getLastRow();
  if (lastRow < 2) return 1;
  const ids = ws.getRange(2, 1, lastRow - 1, 1).getValues().flat()
    .map(v => parseInt(v))
    .filter(v => !isNaN(v));
  return ids.length > 0 ? Math.max(...ids) + 1 : 1;
}

// ── GET ALREADY PROCESSED MESSAGE IDS ───────────────────────
function getProcessedIds(ws) {
  const lastRow = ws.getLastRow();
  if (lastRow < 2) return new Set();
  const emailIdCol = SHEET_COLS.indexOf("Email Message ID") + 1;
  const ids = ws.getRange(2, emailIdCol, lastRow - 1, 1).getValues().flat()
    .filter(v => v !== "");
  return new Set(ids);
}

// ── MAIN SCAN FUNCTION (runs every 30 min) ───────────────────
function scanGmailForTasks() {
  Logger.log("🔍 Starting Gmail scan at " + new Date().toLocaleString());

  ensureSheetHeader();
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(SHEET_NAME);
  const processedIds = getProcessedIds(ws);
  const processedLabel = GmailApp.getUserLabelByName(LABEL_NAME);

  // Search for emails in last 2 hours (overlapping window to catch edge cases)
  const queries = [
    `to:${MY_EMAIL} newer_than:2h`,
    `cc:${MY_EMAIL} newer_than:2h`,
  ];

  const newTasksAdded = [];

  queries.forEach(query => {
    const threads = GmailApp.search(query, 0, 50);
    threads.forEach(thread => {
      const messages = thread.getMessages();
      messages.forEach(msg => {
        const msgId = msg.getId();
        if (processedIds.has(msgId)) return; // Already processed

        const subject  = msg.getSubject() || "";
        const body     = msg.getPlainBody() || "";
        const sender   = msg.getFrom() || "";
        const date_    = msg.getDate();

        // Skip promotions, notifications, automated
        const skipSenders = ["noreply","mailer","notification","no-reply",
          "indigo","amazon","jio","doodle","makemytrip","booking.com",
          "agoda","qureos","wetransfer","themediaant","google.com"];
        if (skipSenders.some(s => sender.toLowerCase().includes(s))) return;

        if (isTaskEmail(subject, body)) {
          const centre   = detectCentre(subject, body);
          const snippet  = body.substring(0, 300).replace(/\n/g, " ");
          const taskId   = getNextId(ws);
          const today    = Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd");
          const now      = Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd HH:mm");

          const row = [
            taskId, centre, "Operations",
            subject.substring(0, 200),
            "", 0,
            "Pending", "",
            "Dr. Vaisakh V S", "Email",
            `From: ${sender}\nDate: ${date_}\n${snippet}`,
            "", today, now, msgId
          ];

          ws.appendRow(row);
          processedIds.add(msgId);
          newTasksAdded.push({ subject, sender, centre });
          Logger.log(`✅ New task added: ${subject} | Centre: ${centre}`);
        }

        // Label as processed
        if (processedLabel) {
          try { thread.addLabel(processedLabel); } catch(e) {}
        }
      });
    });
  });

  // Notify if new tasks found
  if (newTasksAdded.length > 0) {
    const body = newTasksAdded.map(t =>
      `• [${t.centre}] ${t.subject}\n  From: ${t.sender}`
    ).join("\n\n");

    GmailApp.sendEmail(
      NOTIFY_EMAIL,
      `🔔 TaskFlow: ${newTasksAdded.length} new task(s) detected`,
      `Hi Vaisakh,\n\nTaskFlow detected ${newTasksAdded.length} new task(s) from your emails:\n\n${body}\n\nOpen your TaskFlow app to review and update status.\n\n— TaskFlow Auto-Scanner`
    );
    Logger.log(`📧 Notification sent for ${newTasksAdded.length} new tasks.`);
  }

  Logger.log("✅ Gmail scan complete. Tasks added: " + newTasksAdded.length);
}

// ── DAILY SUMMARY (runs at 8 AM) ────────────────────────────
function sendDailySummary() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(SHEET_NAME);
  if (!ws) return;

  const data = ws.getDataRange().getValues();
  if (data.length < 2) return;

  const headers = data[0];
  const idxStatus   = headers.indexOf("Status");
  const idxCentre   = headers.indexOf("Centre");
  const idxTitle    = headers.indexOf("Title");
  const idxOverdue  = headers.indexOf("Days Overdue");
  const idxPriority = headers.indexOf("Priority");

  const rows = data.slice(1);
  const active = rows.filter(r => !["Done","Rejected"].includes(r[idxStatus]));
  const overdue = active.filter(r => parseInt(r[idxOverdue]) > 0)
    .sort((a,b) => b[idxOverdue] - a[idxOverdue]);
  const highPri = active.filter(r => r[idxPriority] === "High" && !(parseInt(r[idxOverdue]) > 0));
  const pending = active.filter(r => !overdue.includes(r) && !highPri.includes(r)).slice(0, 10);

  let emailBody = `Good morning Vaisakh! 🌅\n\nHere's your TaskFlow summary for ${new Date().toDateString()}:\n\n`;
  emailBody += `📊 OVERVIEW\n`;
  emailBody += `• Total active tasks: ${active.length}\n`;
  emailBody += `• Overdue: ${overdue.length}\n`;
  emailBody += `• High priority (not overdue): ${highPri.length}\n\n`;

  if (overdue.length > 0) {
    emailBody += `🔴 OVERDUE TASKS (${overdue.length})\n`;
    overdue.slice(0,15).forEach(r => {
      emailBody += `• [${r[idxCentre]}] ${r[idxTitle]} — ${r[idxOverdue]} days overdue\n`;
    });
    emailBody += "\n";
  }

  if (highPri.length > 0) {
    emailBody += `⭐ HIGH PRIORITY\n`;
    highPri.slice(0,10).forEach(r => {
      emailBody += `• [${r[idxCentre]}] ${r[idxTitle]}\n`;
    });
    emailBody += "\n";
  }

  if (pending.length > 0) {
    emailBody += `🔵 OTHER PENDING\n`;
    pending.forEach(r => {
      emailBody += `• [${r[idxCentre]}] ${r[idxTitle]}\n`;
    });
    emailBody += "\n";
  }

  emailBody += `\nHave a productive day!\n— TaskFlow`;

  GmailApp.sendEmail(
    NOTIFY_EMAIL,
    `📋 TaskFlow Daily Summary — ${new Date().toDateString()}`,
    emailBody
  );
  Logger.log("Daily summary sent.");
}

// ── MANUAL TRIGGER: Scan now ─────────────────────────────────
function scanNow() {
  scanGmailForTasks();
}
