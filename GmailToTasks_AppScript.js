/**
 * RheumaCARE Growth Manager - Gmail → Tasks (AI-powered)
 *
 * Paste this entire file into Google Apps Script:
 *   script.google.com → your project → Code.gs → replace all → Save
 *
 * Then set a trigger: Triggers → Add Trigger → scanGmailAndAddTasks
 *   → Time-driven → Minutes timer → Every 30 minutes
 */

// ── CONFIG ────────────────────────────────────────────────────────────────────
var SHEET_ID      = "1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE";
var SHEET_TAB     = "Master Tasks";
var MY_EMAIL      = "projects@rheumacare.com";
var ANTHROPIC_KEY = PropertiesService.getScriptProperties().getProperty("ANTHROPIC_KEY");
var CLAUDE_MODEL  = "claude-haiku-4-5-20251001";

var CENTRES    = ["Nettoor","Kumbalam","Trivandrum","Bhubaneswar","Kannur","Changanassery","Guwahati","Kollam","Mysore","Bangalore","Ahmedabad","Visakhapatnam","Others"];
var CATEGORIES = ["Civil Work","Admin / Hardware","Regulatory / Licence","IT / Systems","QMS / HMS","Operations","Finance","HR / Admin","Legal / Contracts","Other"];
var SHEET_COLS = ["ID","Centre","Category","Title","Due Date","Days Overdue","Status","Priority","Owner","Source","Notes","Reassigned To","Date Added","Last Updated","Email Message ID"];

// ── MAIN FUNCTION (triggered every 30 min) ────────────────────────────────────
function scanGmailAndAddTasks() {
  var props       = PropertiesService.getScriptProperties();
  var lastRun     = props.getProperty("LAST_RUN_MS");
  var processedIds= JSON.parse(props.getProperty("PROCESSED_IDS") || "[]");

  // Default: scan last 2 days on first run
  var since = lastRun ? new Date(parseInt(lastRun)) : new Date(Date.now() - 2*24*60*60*1000);
  var sinceStr = Utilities.formatDate(since, "GMT", "yyyy/MM/dd");

  // Search for emails TO me (or CC'd) since last run
  var query = "to:" + MY_EMAIL + " after:" + sinceStr;
  var threads = GmailApp.search(query, 0, 50);

  Logger.log("Found " + threads.length + " threads since " + sinceStr);

  var sheet    = SpreadsheetApp.openById(SHEET_ID).getSheetByName(SHEET_TAB);
  var allData  = sheet.getDataRange().getValues();
  var maxId    = 0;
  var existingMsgIds = {};

  for (var i = 1; i < allData.length; i++) {
    var rowId  = parseInt(allData[i][0]) || 0;
    var msgId  = String(allData[i][14] || "").trim(); // Email Message ID column
    if (rowId > maxId) maxId = rowId;
    if (msgId) existingMsgIds[msgId] = true;
  }

  var addedCount = 0;

  for (var t = 0; t < threads.length; t++) {
    var messages = threads[t].getMessages();
    // Only process the LATEST message in each thread
    var msg     = messages[messages.length - 1];
    var msgId   = msg.getId();

    // Skip if already processed
    if (existingMsgIds[msgId] || processedIds.indexOf(msgId) !== -1) continue;
    // Skip if older than last run
    if (lastRun && msg.getDate().getTime() <= parseInt(lastRun)) continue;

    var subject = msg.getSubject() || "";
    var body    = msg.getPlainBody() || "";
    var from    = msg.getFrom() || "";

    // Skip non-actionable emails
    if (isNotActionable(subject, from, body)) {
      processedIds.push(msgId);
      continue;
    }

    // Call Claude AI to extract tasks
    var tasks = parseWithClaude(subject, body, from);

    for (var k = 0; k < tasks.length; k++) {
      var task = tasks[k];
      if (!task.title || task.title.length < 5) continue;

      maxId++;
      var now = new Date();
      var row = [];
      for (var c = 0; c < SHEET_COLS.length; c++) {
        switch (SHEET_COLS[c]) {
          case "ID":               row.push(maxId); break;
          case "Centre":           row.push(task.centre || "Others"); break;
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
          case "Email Message ID": row.push(k === 0 ? msgId : ""); break; // only first task gets msgId
          default:                 row.push("");
        }
      }
      sheet.appendRow(row);
      addedCount++;
    }

    processedIds.push(msgId);
    Utilities.sleep(500); // rate limit
  }

  // Save state
  props.setProperty("LAST_RUN_MS", String(Date.now()));
  // Keep only last 500 IDs to avoid storage overflow
  if (processedIds.length > 500) processedIds = processedIds.slice(-500);
  props.setProperty("PROCESSED_IDS", JSON.stringify(processedIds));

  Logger.log("Added " + addedCount + " new tasks.");
}

// ── CLAUDE AI PARSER ──────────────────────────────────────────────────────────
function parseWithClaude(subject, body, from) {
  var text = "Subject: " + subject + "\nFrom: " + from + "\n\n" + body.substring(0, 3000);

  var prompt = "You are a task extraction assistant for Dr. Vaisakh VS, Growth Manager at RheumaCARE (multi-centre rheumatology clinic chain in India).\n\n" +
    "Extract EVERY distinct actionable task from this email. Return ONLY a raw JSON array, no explanation, no markdown:\n" +
    "[\n" +
    "  {\n" +
    "    \"title\": \"short actionable verb-first title, max 150 chars\",\n" +
    "    \"centre\": \"exactly one of: Nettoor, Kumbalam, Trivandrum, Bhubaneswar, Kannur, Changanassery, Guwahati, Kollam, Mysore, Bangalore, Ahmedabad, Visakhapatnam, Others\",\n" +
    "    \"category\": \"exactly one of: Civil Work, Admin / Hardware, Regulatory / Licence, IT / Systems, QMS / HMS, Operations, Finance, HR / Admin, Legal / Contracts, Other\",\n" +
    "    \"priority\": \"High, Medium, or Low\",\n" +
    "    \"notes\": \"key context - who asked, amounts, deadlines, any specifics\"\n" +
    "  }\n" +
    "]\n\n" +
    "If this email has NO actionable task for Dr. Vaisakh, return []\n\n" +
    "Email:\n" + text;

  try {
    var response = UrlFetchApp.fetch("https://api.anthropic.com/v1/messages", {
      method: "post",
      headers: {
        "x-api-key": ANTHROPIC_KEY,
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
      return fallbackParse(subject, body, from);
    }

    var raw = JSON.parse(response.getContentText()).content[0].text.trim();
    // Strip markdown fences if any
    raw = raw.replace(/^```(?:json)?/, "").replace(/```$/, "").trim();
    var tasks = JSON.parse(raw);

    // Validate fields
    tasks = tasks.filter(function(t) { return t && t.title; });
    tasks.forEach(function(t) {
      if (CENTRES.indexOf(t.centre) === -1)    t.centre   = "Others";
      if (CATEGORIES.indexOf(t.category) === -1) t.category = "Operations";
      if (["High","Medium","Low"].indexOf(t.priority) === -1) t.priority = "Medium";
    });
    return tasks;

  } catch(e) {
    Logger.log("Claude parse error: " + e);
    return fallbackParse(subject, body, from);
  }
}

// ── KEYWORD FALLBACK ──────────────────────────────────────────────────────────
function fallbackParse(subject, body, from) {
  var text = (subject + " " + body).toLowerCase();

  var centre = "Others";
  var centreMap = {
    "Nettoor":["nettoor","nettur","kochi","cochin"],"Kumbalam":["kumbalam"],
    "Trivandrum":["trivandrum","tvm"],"Bhubaneswar":["bhubaneswar","bbsr","odisha"],
    "Kannur":["kannur"],"Changanassery":["changanassery"],
    "Guwahati":["guwahati","gauhati","assam"],"Kollam":["kollam"],
    "Mysore":["mysore","mysuru"],"Bangalore":["bangalore","bengaluru","blr"],
    "Ahmedabad":["ahmedabad","gujarat"],"Visakhapatnam":["visakhapatnam","vizag","vsk"]
  };
  for (var c in centreMap) {
    if (centreMap[c].some(function(k){ return text.indexOf(k) !== -1; })) { centre = c; break; }
  }

  var category = "Operations";
  if (/server|internet|wifi|bsnl|airtel|network|ups|smps|sip|broadband/.test(text)) category = "IT / Systems";
  else if (/payment|invoice|bill|advance|gst|rs\.|rupee|lakh|fees|expense/.test(text)) category = "Finance";
  else if (/noc|licence|license|nabl|nabh|drug|compliance|statutory|registration/.test(text)) category = "Regulatory / Licence";
  else if (/civil|construction|partition|ceiling|electrical|renovation/.test(text)) category = "Civil Work";
  else if (/printer|ac|inverter|furniture|equipment|xray|x-ray|scanner/.test(text)) category = "Admin / Hardware";
  else if (/lease|agreement|contract|deed|legal|lawyer/.test(text)) category = "Legal / Contracts";
  else if (/emr|token|op calling|impactin|hms/.test(text)) category = "QMS / HMS";

  var priority = /urgent|asap|approve|approval|invoice|payment|advance|overdue|rs\./.test(text) ? "High" : "Medium";

  var title = subject.replace(/^(re:|fwd?:|fw:)\s*/i, "").trim().substring(0, 150) ||
              body.split(/[\.\n]/)[0].trim().substring(0, 150);

  return [{ title: title, centre: centre, category: category, priority: priority,
            notes: "From: " + from + " | " + body.substring(0, 300) }];
}

// ── SKIP FILTER ───────────────────────────────────────────────────────────────
function isNotActionable(subject, from, body) {
  var s = subject.toLowerCase(), f = from.toLowerCase(), b = body.substring(0, 500).toLowerCase();

  if (/leave thread|otp|verification code|delivered:|shipped:|order confirm|ebill|your amazon|shipment/.test(s)) return true;
  if (/amazon\.in|jio\.com|qureos|amazonpay|airtel\.in|no-reply@accounts\.google|shipment-tracking/.test(f)) return true;
  if (/^ok$|^sure$|^noted$|^thanks$/.test(b.trim())) return true;

  return false;
}

// ── ONE-TIME BACKFILL (run manually if needed) ────────────────────────────────
function backfillSince(daysAgo) {
  var props = PropertiesService.getScriptProperties();
  props.setProperty("LAST_RUN_MS", String(Date.now() - daysAgo * 24 * 60 * 60 * 1000));
  props.setProperty("PROCESSED_IDS", "[]");
  scanGmailAndAddTasks();
}
