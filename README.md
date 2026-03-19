# ✅ TaskFlow — Dr. Vaisakh VS · RheumaCARE

Sheet: https://docs.google.com/spreadsheets/d/1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE/edit

## Accounts
| What | Account |
|------|---------|
| Gmail scanning, Sheet, data | projects@rheumacare.com |
| GitHub, Streamlit, Google Cloud | drvaisakh.rheumacare@gmail.com |

## Step 1 — Apps Script (projects@rheumacare.com)
1. Open TaskFlow Sheet → Extensions → Apps Script
2. Delete existing code → paste STEP1_apps_script.js contents
3. Save → Run → scanNow (authorize) → Run → setupTriggers
4. Done — Gmail scanned every 30 min automatically ✅

## Step 2 — Google Cloud (drvaisakh.rheumacare@gmail.com)
1. console.cloud.google.com → New project: taskflow-rheuma
2. Enable: Google Sheets API + Google Drive API
3. IAM → Service Accounts → Create → name: taskflow-bot → role: Editor
4. Keys → Add Key → JSON → download
5. Share TaskFlow Sheet with service account email → Editor access

## Step 3 — GitHub (drvaisakh.rheumacare@gmail.com)
1. github.com → New repo → taskflow (private)
2. Upload all files from this zip (except secrets.toml)

## Step 4 — Streamlit Cloud (drvaisakh.rheumacare@gmail.com)
1. share.streamlit.io → New app → select taskflow repo → app.py
2. Advanced settings → Secrets → paste JSON values from Step 2
3. Deploy → live in 2 min 🎉

## Secrets format (paste into Streamlit Cloud)
```toml
sheet_id = "1yjH1pvGUcjq6VNzWUKHRYOepfiUw1pJKjZm1uIn61pE"
[gcp_service_account]
type = "service_account"
project_id = "taskflow-rheuma"
private_key_id = "FROM_JSON"
private_key = "FROM_JSON"
client_email = "taskflow-bot@taskflow-rheuma.iam.gserviceaccount.com"
client_id = "FROM_JSON"
auth_uri = "https://accounts.google.com/o/oauth2/auth"
token_uri = "https://oauth2.googleapis.com/token"
auth_provider_x509_cert_url = "https://www.googleapis.com/oauth2/v1/certs"
client_x509_cert_url = "FROM_JSON"
```
