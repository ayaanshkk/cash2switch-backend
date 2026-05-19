# Renewal customer email automation



Automated reminder emails for electricity (`service_id = 1`) and water (`service_id = 2`) contracts, using `Energy_Contract_Master.contract_end_date` and `Client_Master.client_email`. One email per **bucket** per contract end date (deduped in `Renewal_Email_Send_Log`).



## Database setup



Run the SQL migration once on your PostgreSQL CRM database:



[migrations/sql/20260211_renewal_email_automation.sql](migrations/sql/20260211_renewal_email_automation.sql)



This creates the `Renewal_Email_Send_Log` table only.

## Test customers (temporary)

Script: [backend/scripts/seed_renewal_email_test_customers.py](backend/scripts/seed_renewal_email_test_customers.py)

Creates or updates **one** client (`ayaans1804@gmail.com`) with **four** projects (slot 1–4), each with a contract whose `contract_end_date` is **75 days** from the run date (60–90 day bucket). Two electricity and two water contracts.

```bash
cd cash2switch-backend
python -m backend.scripts.seed_renewal_email_test_customers --tenant-id YOUR_TENANT_ID
python -m backend.scripts.seed_renewal_email_test_customers --dry-run
```

During testing, set a whitelist so only those addresses are mailed:

```text
RENEWAL_EMAIL_TEST_WHITELIST=ayaans1804@gmail.com
```

Remove the variable (or empty it) before production. To clean up DB rows later, delete or archive clients whose company name starts with `[TEST RENEWAL EMAIL]` (respect your FK order: contracts → projects → client, if applicable).

### If the runner shows all zeros

1. Run **`python -m backend.scripts.diagnose_renewal_emails --tenant-id YOUR_TENANT_ID`** — prints seed-tagged contracts, `days_remaining`, whether each row passes the whitelist and the SQL date window.
2. Common cause: **`RENEWAL_EMAIL_TEST_WHITELIST` does not match `Client_Master.client_email`** (e.g. whitelist set to `ayaans1804@gmail.com` but DB rows still use older test addresses). Re-run the seed script after changing test emails.
3. Enable **`RENEWAL_EMAIL_DEBUG=1`** and run `python -m backend.scripts.run_renewal_emails` to see `[renewal-debug]` lines in the console.

## Environment variables



| Variable | Required | Purpose |

|----------|----------|---------|

| `RESEND_API_KEY` | Yes (to send) | Resend API key |

| `RENEWAL_EMAIL_FROM` | Yes (to send) | From address, e.g. `Renewals <renewals@yourdomain.com>` (domain must be verified in Resend) |

| `RENEWAL_EMAIL_CRON_SECRET` | Yes (for HTTP cron) | Shared secret; caller sends header `X-Renewal-Email-Cron-Secret` with this value |

| `RENEWAL_EMAIL_DRY_RUN` | Optional | If `true` / `1`, logs “would send” only; no Resend calls and no send-log rows |

| `RENEWAL_EMAIL_TEST_WHITELIST` | Optional (testing) | Comma-separated recipient emails; when set, **only** these addresses receive renewal emails (case-insensitive). Unset in production. |

| `RENEWAL_EMAIL_SEED_TENANT_ID` | Optional | Used by the seed script when `--tenant-id` is omitted |

| `RENEWAL_EMAIL_DEBUG` | Optional | `1` / `true`: verbose `[renewal-debug]` logs; `run_renewal_emails` also enables INFO logging to the console. |



## Daily schedule



### Option A: HTTP cron (any host)



`POST https://<your-backend-host>/internal/cron/renewal-emails`  

Header: `X-Renewal-Email-Cron-Secret: <same as RENEWAL_EMAIL_CRON_SECRET>`  

Optional JSON body: `{"tenant_id": 1}` for a single-tenant test run.



If `RENEWAL_EMAIL_CRON_SECRET` is unset, the endpoint returns **503** (disabled).



### Option B: Windows Task Scheduler



1. Create `RENEWAL_EMAIL_CRON_SECRET` in your `.env` (long random string).

2. Daily task: **Action** → **Start a program**  

   - Program: `powershell.exe`  

   - Arguments (adjust paths and secret):



```text

-NoProfile -Command "Invoke-RestMethod -Method Post -Uri 'http://127.0.0.1:5000/internal/cron/renewal-emails' -Headers @{ 'X-Renewal-Email-Cron-Secret' = 'YOUR_SECRET_HERE' }"

```



Use your real public API URL if the Flask app runs on another machine.



### Option C: CLI (manual or scheduler)



From the `cash2switch-backend` directory (with `.env` present):



```bash

python -m backend.scripts.run_renewal_emails

python -m backend.scripts.run_renewal_emails --tenant-id 1

python -m backend.scripts.run_renewal_emails --dry-run

```



## Buckets (days until `contract_end_date`)



- **60–90** days: `renewal_60_90`

- **91–180** days: `renewal_91_180`

- **181–365** days: `renewal_180_plus`



Contracts outside **60–365** days are not emailed.

