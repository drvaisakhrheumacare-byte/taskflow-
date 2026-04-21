/**
 * ╔══════════════════════════════════════════════════════════════╗
 * ║      TaskFlow — Gmail Scanner + Claude AI + Smart Digest    ║
 * ║      Account  : projects@rheumacare.com                     ║
 * ║      Sheet ID : 1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE ║
 * ╚══════════════════════════════════════════════════════════════╝
 *
 * SCHEDULE:
 *   • Gmail scanned silently every 30 min (NO individual emails)
 *   • Digest email at 7:30 AM IST — except Sundays
 *   • Digest email at 1:00 PM IST — except Sundays
 *   • Zero emails on Sundays
 *
 * CONFLICT HANDLING:
 *   • One task per email thread (not per message) — no duplicates
 *   • If task marked Done but new email arrives → "Reopened" task created
 *   • Contradicting emails → both logged as notes, you decide
 *
 * INSTALL:
 *   1. Extensions → Apps Script → delete all → paste this
 *   2. Fill CLAUDE_API_KEY below
 *   3. Save → Run → setupTriggers → Authorize
 */

// ── CONFIGURATION ─────────────────────────────────────────────
const MY_EMAIL      = "projects@rheumacare.com";
const NOTIFY_EMAIL  = "projects@rheumacare.com";
const SHEET_ID      = "1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE";
const SHEET_NAME    = "Master Tasks";
const SCAN_LABEL    = "TaskFlow/Processed";
const CLAUDE_API_KEY = "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";
// Get from: https://console.anthropic.com → API Keys → Create Key

const STREAMLIT_URL = "https://lkvnx8pqwynp4cjih9vana.streamlit.app/";
// e.g. https://taskflow-drvaisakh.streamlit.app

// ⚠️ Column order MUST match app.py exactly — do not reorder
const SHEET_COLS = [
  "ID","Centre","Category","Title","Due Date","Days Overdue",
  "Status","Priority","Owner","Source","Notes",
  "Reassigned To","Date Added","Last Updated",
  "Email Message ID","Parent ID"
];

// Senders to always ignore completely
const SKIP_SENDERS = [
  "projects@rheumacare.com",        // never process own emails / TaskFlow notifications
  "noreply","no-reply","mailer-daemon",
  "notifications","notification@",
  "indigo","amazon","jio","doodle","makemytrip","booking.com",
  "agoda","qureos","wetransfer","themediaant",
  "linkedin","twitter","facebook","instagram","youtube",
  "flipkart","swiggy","zomato","uber","ola","paytm","phonepe",
  "hdfc","icici","sbi","axis","kotak",
  "alerts@","billing@","invoice@","payment@",
  "bsnl","airtel","vodafone","jiomail",
  "noreply-apps-scripts","drive-shares-dm-noreply",
  "calendar-notification","accounts-noreply",
  "google.com","googlemail.com",
  "zoho-books","message-service@sender"
];

// ── SHEET HELPERS ─────────────────────────────────────────────
function getSheet() {
  const ss = SpreadsheetApp.openById(SHEET_ID);
  let ws = ss.getSheetByName(SHEET_NAME);
  if (!ws) {
    ws = ss.insertSheet(SHEET_NAME);
    ws.getRange(1,1,1,SHEET_COLS.length).setValues([SHEET_COLS])
      .setFontWeight("bold")
      .setBackground("#1C2030")
      .setFontColor("#E8EAFF");
    ws.setFrozenRows(1);
    ws.setColumnWidth(4, 400);   // Title
    ws.setColumnWidth(11, 350);  // Notes
    ws.setColumnWidth(15, 180);  // Email Message ID
  }
  return ws;
}

function getNextId(ws) {
  const last = ws.getLastRow();
  if (last < 2) return 1;
  const ids = ws.getRange(2,1,last-1,1).getValues().flat()
    .map(v => parseInt(v)).filter(v => !isNaN(v));
  return ids.length ? Math.max(...ids)+1 : 1;
}

function getAllRows(ws) {
  const last = ws.getLastRow();
  if (last < 2) return [];
  return ws.getRange(2,1,last-1,SHEET_COLS.length).getValues();
}

// Returns Set of processed message IDs
function getProcessedMsgIds(rows) {
  const col = SHEET_COLS.indexOf("Email Message ID");
  return new Set(rows.map(r => r[col]).filter(v => v !== ""));
}

// Returns map of threadId → {rowIndex, status, title}
// Thread ID is stored in Notes as "ThreadID:abc123" (no dedicated column)
function getThreadMap(rows) {
  const nCol  = SHEET_COLS.indexOf("Notes");
  const sCol  = SHEET_COLS.indexOf("Status");
  const ttCol = SHEET_COLS.indexOf("Title");
  const idCol = SHEET_COLS.indexOf("ID");
  const map   = {};
  rows.forEach((r, i) => {
    const notes    = String(r[nCol] || "");
    const thrMatch = notes.match(/ThreadID:([^\s|\n]+)/);
    if (thrMatch) map[thrMatch[1]] = { rowIndex: i+2, status: r[sCol], title: r[ttCol], id: r[idCol] };
  });
  return map;
}

function nowIST() {
  return Utilities.formatDate(new Date(),"Asia/Kolkata","yyyy-MM-dd HH:mm");
}
function todayIST() {
  return Utilities.formatDate(new Date(),"Asia/Kolkata","yyyy-MM-dd");
}
function isSunday() {
  return new Date().getDay() === 0;
}

// ── CLAUDE AI PARSER ──────────────────────────────────────────
/**
 * parseWithClaude — returns an ARRAY of task objects (one email can have multiple tasks)
 * Returns [] if no tasks found
 */
function parseWithClaude(subject, from, body, date_) {
  if (!CLAUDE_API_KEY || CLAUDE_API_KEY.includes("PASTE_YOUR")) {
    const t = fallbackParse(subject, from, body);
    return t ? [t] : [];
  }

  const prompt = `You are a task extraction assistant for Dr. Vaisakh VS, Manager - Growth at RheumaCARE / CHARM Healthcare Pvt Ltd, India.

His email: projects@rheumacare.com
His role: Manages new centre projects — civil works, IT/server setup, regulatory licences (Fire NOC, KSEB, KWA, KEIL, Elevator), QMS/HMS systems, procurement, legal contracts, operations across centres: Kumbalam, Kollam, Guwahati, Mysuru, Visakhapatnam, Bengaluru, Kochi, Thiruvananthapuram, Kannur, Changanassery, Bhubaneswar, Ahmedabad.
Key people: Dr. Padmanabha Shenoy (MD/boss), Rithika Ardeshir (Director), Aashind Menon (Founder's office), Krishna Chandran (Head of Operations), Peter Selvaraj (Founder's office).

EMAIL:
From: ${from}
Date: ${date_}
Subject: ${subject}
Body: ${body.substring(0,2500)}

IMPORTANT: A SINGLE EMAIL CAN CONTAIN MULTIPLE SEPARATE TASKS. Extract ALL of them.
Examples of multi-task emails:
- "Please initiate Kannur relocation AND follow up on Mysore PA room AND confirm Kollam payment" → 3 tasks
- "Kindly check server issue in Vizag, also arrange AC for Changanassery, and share procurement list" → 3 tasks

TASK DETECTION RULES:
✅ CREATE a task for each distinct action item Vaisakh needs to personally do
✅ Each task should be for a specific action — approve, initiate, confirm, coordinate, follow up, arrange, check, share, review, process
✅ If email is from vendor/contractor following up — that is a task (respond/process/approve)
❌ SKIP items that are purely FYI with no action from Vaisakh
❌ SKIP items where someone else is actioning and Vaisakh is only CC'd for awareness
❌ SKIP payment receipts, bank transfers, OTPs, automated emails
❌ SKIP items already resolved in the thread

Respond ONLY with this exact JSON array (even if only one task or zero tasks):
[
  {
    "title": "Action-oriented title starting with a verb, max 120 chars. Be specific — include amounts, centre name, item name where relevant. E.g. 'Approve AC unit quote for Changanassery pharmacy (₹40,400)'",
    "centre": "exact name from: Kumbalam, Kollam, Guwahati, Mysuru, Visakhapatnam, Bengaluru, Kochi, Thiruvananthapuram, Kannur, Changanassery, Bhubaneswar, Ahmedabad, General",
    "category": "one of: Civil Work, Admin / Hardware, Regulatory / Licence, IT / Systems, QMS / HMS, Operations, Finance, HR / Admin, Legal / Contracts, Other",
    "priority": "High if urgent/critical/from Dr. Shenoy directly/overdue payment, Medium if normal follow-up, Low if low stakes",
    "due_date": "YYYY-MM-DD if a specific date is mentioned, else empty string",
    "reason": "one short sentence — what exactly does Vaisakh need to do"
  }
]

If no tasks found for Vaisakh, return an empty array: []`;

  try {
    const resp = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "x-api-key": CLAUDE_API_KEY,
        "anthropic-version": "2023-06-01"
      },
      payload: JSON.stringify({
        model: "claude-haiku-4-5-20251001",
        max_tokens: 1000,
        messages: [{ role: "user", content: prompt }]
      }),
      muteHttpExceptions: true
    });

    const data = JSON.parse(resp.getContentText());
    if (data.error) {
      Logger.log("Claude error: "+JSON.stringify(data.error));
      const t = fallbackParse(subject,from,body);
      return t ? [t] : [];
    }

    const text = data.content[0].text.trim();
    // Extract JSON array from response
    const match = text.match(/\[[\s\S]*\]/);
    if (!match) {
      const t = fallbackParse(subject,from,body);
      return t ? [t] : [];
    }

    const tasks = JSON.parse(match[0]);
    Logger.log(`Claude found ${tasks.length} task(s) in email: ${subject}`);
    tasks.forEach((t,i) => Logger.log(`  Task ${i+1}: [${t.centre}] ${t.title}`));
    return tasks;

  } catch(e) {
    Logger.log("Claude exception: "+e.message);
    const t = fallbackParse(subject,from,body);
    return t ? [t] : [];
  }
}

// ── FALLBACK KEYWORD PARSER — returns array like Claude ────────
function fallbackParse(subject, from, body) {
  const text = (subject+" "+body).toLowerCase();

  const skipKw = [
    "payment received","otp","one time password","transaction","debited",
    "credited","bill generated","statement","your booking","flight ticket",
    "hotel booking","order confirmed","delivery","tracking","unsubscribe",
    "promotional","newsletter","offer","discount","leave approved",
    "attendance","payslip","salary credited"
  ];
  if (skipKw.some(k => text.includes(k))) return null;

  const taskKw = [
    "please","kindly","action required","do the needful","ensure",
    "coordinate","can you","could you","please check","please share",
    "please confirm","please do","please arrange","please review",
    "request you","need you to","vaisakh","vaishak","dr. vaisakh",
    "please look into","please handle","please initiate","please proceed",
    "please update","please process","please verify","please approve",
    "take action","following up","reminder","urgent","please coordinate",
    "action needed","your approval","assigned to you","kindly initiate",
    "kindly update","kindly arrange","kindly confirm","kindly coordinate"
  ];
  if (!taskKw.some(k => text.includes(k))) return null;

  const centreMap = {
    "Kumbalam":["kumbalam","kbl"],"Kollam":["kollam","qlnla","qln"],
    "Guwahati":["guwahati","guw"],"Mysuru":["mysuru","mysore","mys"],
    "Visakhapatnam":["vizag","visakhapatnam","vsk"],
    "Bengaluru":["bengaluru","bangalore","blr"],
    "Kochi":["kochi","cochin","ernakulam"],
    "Thiruvananthapuram":["thiruvananthapuram","trivandrum","tvm"],
    "Kannur":["kannur","knn"],"Changanassery":["changanassery","cgs","changanacherry"],
    "Bhubaneswar":["bhubaneswar","bbsr"],"Ahmedabad":["ahmedabad","ahd"]
  };
  let centre = "General";
  for(const [c,kws] of Object.entries(centreMap)) {
    if(kws.some(k => text.includes(k))) { centre=c; break; }
  }

  const catMap = {
    "IT / Systems":["server","hms","impactin","software","network","backup","script","token","database","system"],
    "Civil Work":["civil","construction","partition","plumbing","electrical","interior","hvac","ac unit","hoarding","layout","flooring"],
    "Regulatory / Licence":["noc","licence","license","kseb","kwa","keil","electrical inspectorate","fire","elevator","registration","statutory","compliance"],
    "Finance":["invoice","payment","bill","advance","amount","gst","transfer","reimburse","reimbursement","petty cash","expense"],
    "Legal / Contracts":["agreement","lease","contract","work order","legal","deed","mou","advocate"],
    "QMS / HMS":["qms","queue","token display","patient","touchpoint","workup","referral","hms","calling register"],
    "HR / Admin":["hr","employee","staff","joining","recruitment","designation","leave"],
  };
  let category = "Operations";
  for(const [cat,kws] of Object.entries(catMap)) {
    if(kws.some(k => text.includes(k))) { category=cat; break; }
  }

  const highKw = ["urgent","critical","priority","immediately","asap","emergency","on priority","important"];
  const priority = highKw.some(k => text.includes(k)) ? "High" : "Medium";

  // Return as single-item array to match Claude format
  return [{ title:subject.substring(0,120), centre, category, priority, due_date:"", reason:"Keyword match" }];
}

// ── GMAIL LABEL ───────────────────────────────────────────────
function ensureLabel() {
  const parts = SCAN_LABEL.split("/");
  let path = "";
  parts.forEach(p => {
    path = path ? path+"/"+p : p;
    if (!GmailApp.getUserLabelByName(path)) GmailApp.createLabel(path);
  });
  return GmailApp.getUserLabelByName(SCAN_LABEL);
}

// ── MAIN SCAN (runs every 30 min, silent — no emails sent) ────
function scanGmailForTasks() {
  Logger.log("🔍 Scan started: "+nowIST());
  const ws          = getSheet();
  const allRows     = getAllRows(ws);
  const processedIds= getProcessedMsgIds(allRows);
  const threadMap   = getThreadMap(allRows);
  const label       = ensureLabel();
  const newTasks    = [];
  const reopened    = [];

  // Look back 36h so a skipped trigger run never loses emails;
  // processedIds dedup prevents double-processing
  const queries = [
    `to:${MY_EMAIL} newer_than:36h`,
    `cc:${MY_EMAIL} newer_than:36h`,
  ];

  queries.forEach(query => {
    try {
      GmailApp.search(query, 0, 100).forEach(thread => {
        const threadId  = thread.getId();
        const messages  = thread.getMessages();

        messages.forEach(msg => {
          const msgId = msg.getId();
          if (processedIds.has(msgId)) return;

          const from    = msg.getFrom() || "";
          const subject = msg.getSubject() || "(No Subject)";
          const body    = msg.getPlainBody() || "";
          const date_   = Utilities.formatDate(msg.getDate(),"Asia/Kolkata","yyyy-MM-dd");

          // Skip known automated senders
          const fromLower = from.toLowerCase();
          if (SKIP_SENDERS.some(s => fromLower.includes(s))) {
            try { thread.addLabel(label); } catch(e) {}
            return;
          }

          // ── CONFLICT / THREAD DEDUPLICATION ─────────────────
          if (threadMap[threadId]) {
            const existing = threadMap[threadId];

            if (["Done","Rejected"].includes(existing.status)) {
              // Task was closed but new email arrived — REOPEN
              const ws2 = getSheet();
              const sCol = SHEET_COLS.indexOf("Status")+1;
              const nCol = SHEET_COLS.indexOf("Notes")+1;
              const uCol = SHEET_COLS.indexOf("Last Updated")+1;
              const existingNotes = ws2.getRange(existing.rowIndex, nCol).getValue();
              ws2.getRange(existing.rowIndex, sCol).setValue("Pending");
              ws2.getRange(existing.rowIndex, nCol).setValue(
                existingNotes + `\n\n⚠️ REOPENED ${nowIST()}: New email received\nFrom: ${from}\n${body.substring(0,200)}`
              );
              ws2.getRange(existing.rowIndex, uCol).setValue(nowIST());
              reopened.push({ title: existing.title, from, centre: "", reason:"New email on closed thread" });
              Logger.log(`🔄 Reopened task: ${existing.title}`);
            } else {
              // Task exists and is active — append note about new email (conflict logging)
              const ws2 = getSheet();
              const nCol = SHEET_COLS.indexOf("Notes")+1;
              const uCol = SHEET_COLS.indexOf("Last Updated")+1;
              const existingNotes = ws2.getRange(existing.rowIndex, nCol).getValue();
              ws2.getRange(existing.rowIndex, nCol).setValue(
                existingNotes + `\n\n📧 Follow-up ${nowIST()}\nFrom: ${from}\n${body.substring(0,200)}`
              );
              ws2.getRange(existing.rowIndex, uCol).setValue(nowIST());
              Logger.log(`📎 Follow-up appended to existing task: ${existing.title}`);
            }

            // Mark message as processed
            processedIds.add(msgId);
            try { thread.addLabel(label); } catch(e) {}
            return;
          }

          // ── NEW THREAD — Claude returns ARRAY of tasks ──────
          const tasks = parseWithClaude(subject, from, body, date_);

          if (tasks.length > 0) {
            tasks.forEach((task, idx) => {
              const taskId = getNextId(ws);
              const multiNote = tasks.length > 1 ? ` [Task ${idx+1} of ${tasks.length}]` : "";
              const row = [
                taskId, task.centre, task.category,
                task.title,
                task.due_date || "", 0,
                "Pending", task.priority || "Medium",
                "Dr. Vaisakh V S", "Email",
                // ThreadID stored in Notes so getThreadMap can find it for dedup/reopen
                `From: ${from}\nDate: ${date_}\nSubject: ${subject}${multiNote}\n\nReason: ${task.reason}\n\n${body.substring(0,300)}\n\nThreadID:${threadId}`,
                "", todayIST(), nowIST(),
                msgId,   // col 15 = Email Message ID  (matches app.py)
                ""       // col 16 = Parent ID — empty, set manually via dashboard
              ];
              ws.appendRow(row);
              newTasks.push({ ...task, from, multiNote });
              Logger.log(`✅ Task ${idx+1}/${tasks.length}: [${task.centre}] ${task.title}`);
            });

            // Register thread using first task title for reopen/follow-up detection
            const label_ = tasks.length > 1 ? `${tasks[0].title} (+${tasks.length-1} more)` : tasks[0].title;
            threadMap[threadId] = { rowIndex: ws.getLastRow(), status: "Pending", title: label_ };

          } else {
            Logger.log(`⏭ Not a task: ${subject}`);
          }
          processedIds.add(msgId);

          try { thread.addLabel(label); } catch(e) {}
        });
      });
    } catch(e) {
      Logger.log("Query error: "+e.message);
    }
  });

  // Queue new tasks for next digest (don't email now)
  if (newTasks.length > 0 || reopened.length > 0) {
    const existing = PropertiesService.getScriptProperties().getProperty("pendingDigest");
    const pending  = existing ? JSON.parse(existing) : { newTasks:[], reopened:[] };
    newTasks.forEach(t => pending.newTasks.push(t));
    reopened.forEach(t => pending.reopened.push(t));
    PropertiesService.getScriptProperties().setProperty("pendingDigest", JSON.stringify(pending));
  }

  Logger.log(`✅ Scan done. New: ${newTasks.length}, Reopened: ${reopened.length}`);
}

// ── SEND DIGEST (called at 7:30 AM and 1:00 PM) ───────────────
function sendDigest() {
  // No email on Sundays
  if (isSunday()) { Logger.log("Sunday — no digest sent."); return; }

  const ws   = getSheet();
  const data = ws.getDataRange().getValues();
  if (data.length < 2) return;

  const h        = data[0];
  const rows     = data.slice(1);
  const iStatus  = h.indexOf("Status");
  const iCentre  = h.indexOf("Centre");
  const iTitle   = h.indexOf("Title");
  const iOverdue = h.indexOf("Days Overdue");
  const iPriority= h.indexOf("Priority");
  const iDue     = h.indexOf("Due Date");
  const iAdded   = h.indexOf("Date Added");
  const iCat     = h.indexOf("Category");

  const active   = rows.filter(r => !["Done","Rejected"].includes(r[iStatus]));
  const overdue  = active.filter(r => parseInt(r[iOverdue]) > 0)
                         .sort((a,b) => b[iOverdue]-a[iOverdue]);
  const highPri  = active.filter(r => r[iPriority]==="High" && !(parseInt(r[iOverdue])>0));
  const medium   = active.filter(r => r[iPriority]==="Medium" && !(parseInt(r[iOverdue])>0));
  const rest     = active.filter(r => !overdue.includes(r) && !highPri.includes(r) && !medium.includes(r));
  const today    = todayIST();
  const newToday = active.filter(r => r[iAdded]===today);

  // Get queued new tasks from scan
  const pendingRaw = PropertiesService.getScriptProperties().getProperty("pendingDigest");
  const pending    = pendingRaw ? JSON.parse(pendingRaw) : { newTasks:[], reopened:[] };
  PropertiesService.getScriptProperties().deleteProperty("pendingDigest");

  const hr   = new Date().getHours();
  const slot = hr < 12 ? "🌅 Morning" : "☀️ Afternoon";
  const fmt  = r => `  • [${r[iCentre]}] ${String(r[iTitle]).substring(0,90)}${r[iDue]?" (due "+r[iDue]+")":""}`;

  let body = `${slot} TaskFlow Digest — ${new Date().toDateString()}\n`;
  body    += `${"═".repeat(55)}\n\n`;

  // Overview
  body += `📊 OVERVIEW\n`;
  body += `   Active tasks  : ${active.length}\n`;
  body += `   🔴 Overdue    : ${overdue.length}\n`;
  body += `   ⭐ High pri   : ${highPri.length}\n`;
  body += `   🆕 New today  : ${newToday.length}\n\n`;

  // Newly detected tasks since last digest
  if (pending.newTasks.length > 0) {
    body += `🆕 NEW TASKS SINCE LAST DIGEST (${pending.newTasks.length})\n`;
    body += `${"─".repeat(45)}\n`;
    pending.newTasks.forEach(t => {
      body += `  • [${t.centre}] ${t.title}\n`;
      body += `    From: ${t.from}${t.priority?" | ⭐ "+t.priority:""}\n`;
    });
    body += "\n";
  }

  // Reopened tasks
  if (pending.reopened.length > 0) {
    body += `🔄 REOPENED TASKS (new email on closed task) (${pending.reopened.length})\n`;
    body += `${"─".repeat(45)}\n`;
    pending.reopened.forEach(t => {
      body += `  • ${t.title}\n    From: ${t.from}\n`;
    });
    body += "\n";
  }

  // Overdue
  if (overdue.length > 0) {
    body += `🔴 OVERDUE — Act now (${overdue.length})\n`;
    body += `${"─".repeat(45)}\n`;
    overdue.slice(0,20).forEach(r => body += fmt(r)+` — ${r[iOverdue]}d overdue\n`);
    body += "\n";
  }

  // High priority
  if (highPri.length > 0) {
    body += `⭐ HIGH PRIORITY (${highPri.length})\n`;
    body += `${"─".repeat(45)}\n`;
    highPri.slice(0,10).forEach(r => body += fmt(r)+"\n");
    body += "\n";
  }

  // Medium priority
  if (medium.length > 0) {
    body += `🔵 MEDIUM PRIORITY (${medium.length})\n`;
    body += `${"─".repeat(45)}\n`;
    medium.slice(0,10).forEach(r => body += fmt(r)+"\n");
    body += "\n";
  }

  // Rest
  if (rest.length > 0) {
    body += `📋 OTHER PENDING (${Math.min(rest.length,10)} of ${rest.length})\n`;
    body += `${"─".repeat(45)}\n`;
    rest.slice(0,10).forEach(r => body += fmt(r)+"\n");
    if (rest.length > 10) body += `  ... and ${rest.length-10} more in the app\n`;
    body += "\n";
  }

  body += `\n🔗 Open TaskFlow: ${STREAMLIT_URL}\n`;
  body += `\n— TaskFlow Auto-Scanner (next digest: ${hr < 12 ? "1:00 PM" : "7:30 AM tomorrow"})`;

  const subj = `${slot} Digest — ${overdue.length} overdue · ${pending.newTasks.length} new · ${active.length} active`;
  GmailApp.sendEmail(NOTIFY_EMAIL, subj, body);
  Logger.log(`✅ ${slot} digest sent.`);
}

// ── UPDATE OVERDUE COUNTS ─────────────────────────────────────
function updateOverdueDays() {
  const ws   = getSheet();
  const data = ws.getDataRange().getValues();
  if (data.length < 2) return;
  const h       = data[0];
  const iDue    = h.indexOf("Due Date");
  const iOv     = h.indexOf("Days Overdue");
  const iStatus = h.indexOf("Status");
  const today   = new Date(); today.setHours(0,0,0,0);
  for (let i = 1; i < data.length; i++) {
    if (["Done","Rejected"].includes(data[i][iStatus])) continue;
    const due = data[i][iDue];
    if (!due) continue;
    const d = new Date(due); d.setHours(0,0,0,0);
    if (isNaN(d.getTime())) continue;
    ws.getRange(i+1, iOv+1).setValue(Math.max(0, Math.floor((today-d)/86400000)));
  }
  Logger.log("Overdue days updated.");
}

// ── SETUP TRIGGERS — run this ONCE manually ───────────────────
function setupTriggers() {
  // Clear ALL existing triggers first
  ScriptApp.getProjectTriggers().forEach(t => ScriptApp.deleteTrigger(t));

  // Gmail scan every 30 minutes (silent)
  ScriptApp.newTrigger("scanGmailForTasks")
    .timeBased().everyMinutes(30).create();

  // Morning digest at 7:30 AM IST = 2:00 AM UTC
  // Apps Script only allows hourly precision — we use hour 2 UTC = ~7:30 AM IST
  ScriptApp.newTrigger("sendDigest")
    .timeBased().atHour(2).everyDays(1).create();

  // Afternoon digest at 1:00 PM IST = 7:30 AM UTC
  ScriptApp.newTrigger("sendDigest")
    .timeBased().atHour(7).everyDays(1).create();

  // Overdue count update at 6:00 AM IST = 12:30 AM UTC
  ScriptApp.newTrigger("updateOverdueDays")
    .timeBased().atHour(1).everyDays(1).create();

  // Ensure sheet is set up
  getSheet();

  Logger.log("✅ Triggers configured:");
  Logger.log("   Gmail scan    : every 30 min (silent)");
  Logger.log("   Morning digest: ~7:30 AM IST (except Sundays)");
  Logger.log("   Afternoon digest: ~1:00 PM IST (except Sundays)");
  Logger.log("   Overdue update: ~6:00 AM IST");
  Logger.log("   Sundays       : zero emails");

  // Run initial scan
  scanGmailForTasks();
  Logger.log("✅ Initial scan complete.");
}

// ── MANUAL TEST FUNCTIONS ─────────────────────────────────────
function scanNow()          { scanGmailForTasks(); }
function digestNow()        { sendDigest(); }
function updateOverdueNow() { updateOverdueDays(); }
