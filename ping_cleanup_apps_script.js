/**
 * ServerStatus Sheet — Auto Cleanup Script
 * ═══════════════════════════════════════════════════════════════
 * SETUP (one time only):
 * 1. Open the PING Google Sheet (ServerStatus sheet)
 *    → https://docs.google.com/spreadsheets/d/1uf4pqKHEAbw6ny7CVZZVMw23PTfmv0QZzdCyj4fU33c
 * 2. Extensions → Apps Script
 * 3. Paste this entire file → Save
 * 4. Run setupCleanupTrigger() once (Run menu → Run function)
 * 5. Authorize when prompted
 *
 * What it does:
 * - Keeps only the latest MAX_ROWS rows in ServerStatus sheet
 * - Deletes the oldest rows (at top) when limit is exceeded
 * - Runs automatically every day at midnight
 * - You can also run cleanServerStatusSheet() manually anytime
 * ═══════════════════════════════════════════════════════════════
 */

const SERVERS_SHEET_NAME = "ServerStatus";
const MAX_ROWS           = 500;   // max data rows to keep (not counting header)
                                   // ~500 rows ≈ last few days of pings

// ── SETUP: Run this once manually ───────────────────────────────
function setupCleanupTrigger() {
  // Remove any existing cleanup triggers to avoid duplicates
  ScriptApp.getProjectTriggers().forEach(t => {
    if (t.getHandlerFunction() === "cleanServerStatusSheet") {
      ScriptApp.deleteTrigger(t);
    }
  });

  // Run cleanup daily at midnight (IST ≈ 18:30 UTC previous day)
  ScriptApp.newTrigger("cleanServerStatusSheet")
    .timeBased()
    .atHour(19)          // ~12:30 AM IST
    .everyDays(1)
    .create();

  Logger.log("✅ Daily cleanup trigger set. Will run every day at ~12:30 AM IST.");
  Logger.log("Running an initial cleanup now...");
  cleanServerStatusSheet();
}

// ── MAIN CLEANUP FUNCTION ────────────────────────────────────────
function cleanServerStatusSheet() {
  const ss = SpreadsheetApp.getActiveSpreadsheet();
  const ws = ss.getSheetByName(SERVERS_SHEET_NAME);

  if (!ws) {
    Logger.log("❌ Sheet '" + SERVERS_SHEET_NAME + "' not found.");
    return;
  }

  const totalRows  = ws.getLastRow();
  const headerRows = 1;
  const dataRows   = totalRows - headerRows;

  Logger.log("📊 Current rows: " + dataRows + " | Limit: " + MAX_ROWS);

  if (dataRows <= MAX_ROWS) {
    Logger.log("✅ Within limit. No cleanup needed.");
    return;
  }

  const rowsToDelete = dataRows - MAX_ROWS;

  // Delete oldest rows (just after header row)
  ws.deleteRows(headerRows + 1, rowsToDelete);

  Logger.log("🗑 Deleted " + rowsToDelete + " oldest row(s). Rows remaining: " + MAX_ROWS);
}

// ── MANUAL: Run cleanup right now ───────────────────────────────
function cleanNow() {
  cleanServerStatusSheet();
}
