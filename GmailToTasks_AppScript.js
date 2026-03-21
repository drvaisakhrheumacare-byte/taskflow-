/**
 * RheumaCARE Growth Manager - Gmail to Tasks (AI-powered)
 *
 * SETUP:
 * 1. Paste into Google Apps Script (script.google.com → Code.gs → replace all → Save)
 * 2. Project Settings → Script Properties → Add property:
 *      Name:  ANTHROPIC_KEY
 *      Value: sk-ant-api03-...
 * 3. Run setupTriggers() once to install the 30-min trigger
 */

// ── CONFIG ─────────────────────────────────────────────────────────────────
var SHEET_ID     = "1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE";
var SHEET_TAB    = "Master Tasks";
var MY_EMAIL     = "projects@rheumacare.com";
var CLAUDE_MODEL = "claude-haiku-4-5-20251001";

var CENTRES = [
  "Nettoor","Kumbalam","Trivandrum","Bhubaneswar","Kannur",
  "Changanassery","Guwahati","Kollam","Mysore","Bangalore",
  "Ahmedabad","Visakhapatnam","Others"
];
var CATEGORIES = [
  "Civil Work","Admin / Hardware","Regulatory / Licence","IT / Systems",
  "QMS / HMS","Operations","Finance","HR / Admin","Legal / Contracts","Other"
];
var SHEET_COLS = [
  "ID","Centre","Category","Title","Due Date","Days Overdue","Status",
  "Priority","Owner","Source","Notes","Reassigned To","Date Added",
  "Last Updated","Email Message ID"
];

// ── SETUP TRIGGERS (run once manually) ─────────────────────────────────────
function setupTriggers() {
  ScriptApp.getProjectTriggers().forEach(function(t) {
    if (t.getHandlerFunction() === "scanGmailAndAddTasks") {
      ScriptApp.deleteTrigger(t);
    }
  });
  ScriptApp.newTrigger("scanGmailAndAddTasks")
    .timeBased()
    .everyMinutes(30)
    .create();
  Logger.log("Trigger created: scanGmailAndAddTasks every 30 minutes.");
}

// ── MAIN FUNCTION ───────────────────────────────────────────────────────────
function scanGmailAndAddTasks() {
  // Skip Sundays
  if (new Date().getDay() === 0) {
    Logger.log("Sunday — skipping.");
    return;
  }

  var props        = PropertiesService.getScriptProperties();
  var lastRunMs    = props.getProperty("LAST_RUN_MS");
  var processedIds = JSON.parse(props.getProperty("PROCESSED_IDS") || "[]");

  var since    = lastRunMs ? new Date(parseInt(lastRunMs)) : new Date(Date.now() - 2*24*60*60*1000);
  var sinceStr = Utilities.formatDate(since, "GMT", "yyyy/MM/dd");

  var query   = "to:" + MY_EMAIL + " after:" + sinceStr;
  var threads = GmailApp.search(query, 0, 50);
  Logger.log("Found " + threads.length + " threads since " + sinceStr);

  var sheet   = SpreadsheetApp.openById(SHEET_ID).getSheetByName(SHEET_TAB);
  var allData = sheet.getDataRange().getValues();

  // Build indexes from existing data
  var maxId        = 0;
  var existingMsgIds = {};  // msgId -> true
  var existingThrIds = {};  // threadId -> sheet row number (1-based)

  for (var i = 1; i < allData.length; i++) {
    var rowId = parseInt(allData[i][0]) || 0;
    if (rowId > maxId) maxId = rowId;

    var msgIdCol = String(allData[i][14] || "").trim();
    if (msgIdCol) existingMsgIds[msgIdCol] = true;

    // ThreadID is stored in Notes as "ThreadID:abc123"
    var notes    = String(allData[i][10] || "");
    var thrMatch = notes.match(/ThreadID:([^\s|]+)/);
    if (thrMatch) existingThrIds[thrMatch[1]] = i + 1; // 1-based row
  }

  var addedCount    = 0;
  var reopenedCount = 0;

  for (var t = 0; t < threads.length; t++) {
    var thread   = threads[t];
    var threadId = thread.getId();
    var messages = thread.getMessages();
    var msg      = messages[messages.length - 1]; // latest message only
    var msgId    = msg.getId();

    // Skip already processed message
    if (existingMsgIds[msgId] || processedIds.indexOf(msgId) !== -1) continue;
    if (lastRunMs && msg.getDate().getTime() <= parseInt(lastRunMs)) continue;

    var subject = msg.getSubject() || "";
    var body    = msg.getPlainBody() || "";
    var from    = msg.getFrom() || "";

    if (isNotActionable(subject, from, body)) {
      processedIds.push(msgId);
      continue;
    }

    // Reopen logic: new reply in thread whose task was already closed
    if (existingThrIds[threadId]) {
      var existingRow = existingThrIds[threadId];
      var statusCol   = SHEET_COLS.indexOf("Status") + 1;
      var curStatus   = sheet.getRange(existingRow, statusCol).getValue();
      if (curStatus === "Done" || curStatus === "Rejected") {
        sheet.getRange(existingRow, statusCol).setValue("Pending");
        var luCol = SHEET_COLS.indexOf("Last Updated") + 1;
        sheet.getRange(existingRow, luCol).setValue(
          Utilities.formatDate(new Date(), "Asia/Kolkata", "yyyy-MM-dd HH:mm")
        );
        Logger.log("Reopened row " + existingRow + " (new reply in thread " + threadId + ")");
        reopenedCount++;
      }
      // Thread already tracked — no new task row needed
      processedIds.push(msgId);
      Utilities.sleep(300);
      continue;
    }

    // New thread — extract tasks via Claude AI
    var tasks = parseWithClaude(subject, body, from, threadId);

    for (var k = 0; k < tasks.length; k++) {
      var task = tasks[k];
      if (!task.title || task.title.length < 5) continue;

      maxId++;
      var now = new Date();
      var row = [];
      for (var c = 0; c < SHEET_COLS.length; c++) {
        switch (SHEET_COLS[c]) {
          case "ID":               row.push(maxId); break;
          case "Centre":           row.push(task.centre   || "Others"); break;
          case "Category":         row.push(task.category || "Operations"); break;
          case "Title":            row.push(task.title.substring(0, 200)); break;
          case "Due Date":         row.push(""); break;
          case "Days Overdue":     row.push(0); break;
          case "Status":           row.push("Pending"); break;
          case "Priority":         row.push(task.priority || "Medium"); break;
          case "Owner":            row.push("Dr. Vaisakh V S"); break;
          case "Source":           row.push("Email"); break;
          case "Notes":            row.push(task.notes || ""); break;
          case "Reassigned To":    row.push(""); break;
          case "Date Added":       row.push(Utilities.formatDate(now, "Asia/Kolkata", "yyyy-MM-dd")); break;
          case "Last Updated":     row.push(Utilities.formatDate(now, "Asia/Kolkata", "yyyy-MM-dd HH:mm")); break;
          case "Email Message ID": row.push(k === 0 ? msgId : ""); break;
          default:                 row.push("");
        }
      }
      sheet.appendRow(row);
      addedCount++;
    }

    processedIds.push(msgId);
    Utilities.sleep(500);
  }

  // Save state
  props.setProperty("LAST_RUN_MS", String(Date.now()));
  if (processedIds.length > 500) processedIds = processedIds.slice(-500);
  props.setProperty("PROCESSED_IDS", JSON.stringify(processedIds));

  Logger.log("Added " + addedCount + " new tasks, reopened " + reopenedCount + ".");
}

// ── CLAUDE AI PARSER ────────────────────────────────────────────────────────
function parseWithClaude(subject, body, from, threadId) {
  var apiKey = PropertiesService.getScriptProperties().getProperty("ANTHROPIC_KEY");
  if (!apiKey) {
    Logger.log("ANTHROPIC_KEY not set in Script Properties — using keyword fallback.");
    return fallbackParse(subject, body, from, threadId);
  }

  var text = "Subject: " + subject + "\nFrom: " + from + "\n\n" + body.substring(0, 3000);

  var prompt =
    "You are a task extraction assistant for Dr. Vaisakh VS, Growth Manager at RheumaCARE " +
    "(multi-centre rheumatology clinic chain in India).\n\n" +
    "Extract EVERY distinct actionable task from this email. Return ONLY a raw JSON array, no explanation, no markdown:\n" +
    "[\n" +
    "  {\n" +
    "    \"title\": \"short actionable verb-first title, max 150 chars\",\n" +
    "    \"centre\": \"exactly one of: Nettoor, Kumbalam, Trivandrum, Bhubaneswar, Kannur, Changanassery, Guwahati, Kollam, Mysore, Bangalore, Ahmedabad, Visakhapatnam, Others\",\n" +
    "    \"category\": \"exactly one of: Civil Work, Admin / Hardware, Regulatory / Licence, IT / Systems, QMS / HMS, Operations, Finance, HR / Admin, Legal / Contracts, Other\",\n" +
    "    \"priority\": \"High, Medium, or Low\",\n" +
    "    \"notes\": \"key context — who asked, amounts, deadlines, specifics. Must end with: | ThreadID:" + threadId + "\"\n" +
    "  }\n" +
    "]\n\n" +
    "Centre name mapping (use the exact name on the right):\n" +
    "  Kochi / Cochin / Nettoor / 0484 → Nettoor\n" +
    "  Thiruvananthapuram / TVM / 0471 → Trivandrum\n" +
    "  Mysuru → Mysore\n" +
    "  Bengaluru / BLR → Bangalore\n" +
    "  Unknown / General / Head Office → Others\n\n" +
    "If this email has NO actionable task for Dr. Vaisakh, return []\n\n" +
    "Email:\n" + text;

  try {
    var response = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", {
      method: "post",
      headers: {
        "x-api-key": apiKey,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json"
      },
      payload: JSON.stringify({
        model: CLAUDE_MODEL,
        max_tokens: 1500,
        messages: [{ role: "user", content: prompt }]
      }),
      muteHttpExceptions: true
    });

    var code = response.getResponseCode();
    if (code !== 200) {
      Logger.log("Claude API error " + code + ": " + response.getContentText());
      return fallbackParse(subject, body, from, threadId);
    }

    var raw = JSON.parse(response.getContentText()).content[0].text.trim();
    raw = raw.replace(/^```(?:json)?/, "").replace(/```$/, "").trim();
    var tasks = JSON.parse(raw);

    tasks = tasks.filter(function(t) { return t && t.title; });
    tasks.forEach(function(t) {
      if (CENTRES.indexOf(t.centre) === -1)      t.centre   = "Others";
      if (CATEGORIES.indexOf(t.category) === -1) t.category = "Operations";
      if (["High","Medium","Low"].indexOf(t.priority) === -1) t.priority = "Medium";
      if (!t.notes) t.notes = "";
      if (t.notes.indexOf("ThreadID:") === -1) t.notes += " | ThreadID:" + threadId;
    });
    return tasks;

  } catch(e) {
    Logger.log("Claude parse error: " + e);
    return fallbackParse(subject, body, from, threadId);
  }
}

// ── KEYWORD FALLBACK ────────────────────────────────────────────────────────
function fallbackParse(subject, body, from, threadId) {
  var text = (subject + " " + body).toLowerCase();

  var centre = "Others";
  var centreMap = {
    "Nettoor":       ["nettoor","nettur","kochi","cochin","0484"],
    "Kumbalam":      ["kumbalam","kbl"],
    "Trivandrum":    ["trivandrum","thiruvananthapuram","tvm","0471"],
    "Bhubaneswar":   ["bhubaneswar","bbsr","odisha"],
    "Kannur":        ["kannur","cannanore"],
    "Changanassery": ["changanassery","changanacherry"],
    "Guwahati":      ["guwahati","gauhati","assam","ira tower","azure properties"],
    "Kollam":        ["kollam","quilon"],
    "Mysore":        ["mysore","mysuru"],
    "Bangalore":     ["bangalore","bengaluru","blr"],
    "Ahmedabad":     ["ahmedabad","gujarat"],
    "Visakhapatnam": ["visakhapatnam","vizag","vsk","vsp"]
  };
  for (var c in centreMap) {
    if (centreMap[c].some(function(k){ return text.indexOf(k) !== -1; })) {
      centre = c; break;
    }
  }

  var category = "Operations";
  if (/server|internet|wifi|bsnl|airtel|jio|network|vpn|router|ups|smps|sip|broadband|cctv/.test(text))
    category = "IT / Systems";
  else if (/payment|invoice|bill|advance|reimburs|gst|rs\.|rupee|lakh|fees|expense|quotation/.test(text))
    category = "Finance";
  else if (/noc|licence|license|nabl|nabh|drug|compliance|inspection|statutory|registration|fire noc|lsgd/.test(text))
    category = "Regulatory / Licence";
  else if (/civil|construction|partition|ceiling|electrical work|xray room|x-ray room|renovation|lab room/.test(text))
    category = "Civil Work";
  else if (/printer|ac unit|inverter|furniture|chair|barcode|scanner|xray|x-ray|dexa|generator/.test(text))
    category = "Admin / Hardware";
  else if (/lease|agreement|contract|deed|registrar|legal|lawyer|relocation|rent/.test(text))
    category = "Legal / Contracts";
  else if (/emr|token display|op calling|calling register|impactin|hms/.test(text))
    category = "QMS / HMS";
  else if (/leave|attendance|staff/.test(text))
    category = "HR / Admin";

  var priority = /urgent|asap|approve|approval|invoice|payment|advance|noc|licence|license|overdue|rs\./.test(text)
    ? "High" : "Medium";

  var title = subject.replace(/^(re:|fwd?:|fw:)\s*/i, "").trim().substring(0, 150) ||
              body.split(/[.\n]/)[0].trim().substring(0, 150);

  var notes = "From: " + from + " | " + body.substring(0, 300) + " | ThreadID:" + threadId;
  return [{ title: title, centre: centre, category: category, priority: priority, notes: notes }];
}

// ── SKIP FILTER ─────────────────────────────────────────────────────────────
function isNotActionable(subject, from, body) {
  var s = subject.toLowerCase();
  var f = from.toLowerCase();
  var b = body.substring(0, 500).toLowerCase();

  if (/leave thread|otp|verification code|delivered:|shipped:|order confirm|ebill|your amazon|shipment|statement/.test(s))
    return true;
  if (/amazon\.in|jio\.com|qureos|amazonpay|airtel\.in|no-reply@accounts\.google|shipment-tracking|auto-confirm|order-update/.test(f))
    return true;
  if (/^ok$|^sure$|^noted$|^thanks$|^ok regards|^sure! on|^no worries/.test(b.trim()))
    return true;

  return false;
}

// ── BACKFILL (run manually if needed) ───────────────────────────────────────
function backfillSince(daysAgo) {
  var props = PropertiesService.getScriptProperties();
  props.setProperty("LAST_RUN_MS", String(Date.now() - daysAgo * 24 * 60 * 60 * 1000));
  props.setProperty("PROCESSED_IDS", "[]");
  scanGmailAndAddTasks();
}
