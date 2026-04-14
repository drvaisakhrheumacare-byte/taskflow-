# TaskFlow — Dr. Vaisakh VS · RheumaCARE

## Accounts
| What | Account |
|------|---------|
| Gmail scanning, Sheet, data | *(configure in secrets.toml)* |
| GitHub, Streamlit, Google Cloud | *(your account)* |

## Step 1 — Apps Script (projects@rheumacare.com)
1. Open TaskFlow Sheet → Extensions → Apps Script
2. Delete existing code → paste STEP1_apps_script.js contents
3. Save → Run → scanNow (authorize) → Run → setupTriggers
4. Done — Gmail scanned every 30 min automatically ✅

## Step 2 — Google Cloud
1. console.cloud.google.com → New project: taskflow-rheuma
2. Enable: Google Sheets API + Google Drive API
3. IAM → Service Accounts → Create → name: taskflow-bot → role: Editor
4. Keys → Add Key → JSON → download
5. Share TaskFlow Sheet with service account email → Editor access

## Step 3 — GitHub
1. github.com → New repo → taskflow (private)
2. Upload all files from this zip (except secrets.toml)

## Step 4 — Streamlit Cloud
1. share.streamlit.io → New app → select taskflow repo → app.py
2. Advanced settings → Secrets → paste JSON values from Step 2
3. Deploy → live in 2 min 🎉

## Secrets format (paste into Streamlit Cloud)
See `.streamlit/secrets.toml.example` for the full template.
```toml
sheet_id      = "YOUR_SHEET_ID"
ping_sheet_id = "YOUR_PING_SHEET_ID"
my_email      = "your-email@example.com"

[users]
username = "password"

[gcp_service_account]
# paste values from your downloaded service account JSON
type = "service_account"
...
```
