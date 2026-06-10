# Renewal customer email automation

Automated reminder emails for electricity (`service_id = 1`) and water (`service_id = 2`) contracts, using `Energy_Contract_Master.contract_end_date` and `Client_Master.client_email`. One email per bucket per contract end date is deduped in `Renewal_Email_Send_Log`.

## Database setup

Run the SQL migration once on your PostgreSQL CRM database:

[migrations/sql/20260211_renewal_email_automation.sql](migrations/sql/20260211_renewal_email_automation.sql)

This creates the `Renewal_Email_Send_Log` table only.

## Test customers

Script: [backend/scripts/seed_renewal_email_test_customers.py](backend/scripts/seed_renewal_email_test_customers.py)

Create test renewal records for all active buckets:

```bash
cd cash2switch-backend
python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 2 --bucket-suite --real-data
```

The script uses `RENEWAL_EMAIL_TEST_WHITELIST` when `--test-email` is omitted, so test records can be created for every whitelisted inbox.

During testing, set a whitelist so only those addresses are mailed:

```text
RENEWAL_EMAIL_TEST_WHITELIST=test1@example.com,test2@example.com
```

Remove the variable, or leave it empty, before production. To clean up DB rows later, delete or archive clients whose company name starts with `[TEST RENEWAL EMAIL]`, respecting your database foreign keys.

### If the runner shows all zeros

1. Run `python -m backend.scripts.diagnose_renewal_emails --tenant-id YOUR_TENANT_ID`.
2. Check that `RENEWAL_EMAIL_TEST_WHITELIST` matches the test customer email addresses.
3. Check whether the same bucket was already sent; `skipped_dup` is expected after the first real send.
4. Enable `RENEWAL_EMAIL_DEBUG=1` and run `python -m backend.scripts.run_renewal_emails --tenant-id YOUR_TENANT_ID`.

## Environment variables

| Variable | Required | Purpose |
|----------|----------|---------|
| `DATABASE_URL` | Yes | PostgreSQL CRM database connection |
| `RESEND_API_KEY` | Yes, to send | Resend API key |
| `RENEWAL_EMAIL_FROM` | Yes, to send | From address, e.g. `Business Gas Renewals <renewals@businessgas.com>`; domain must be verified in Resend |
| `RENEWAL_EMAIL_CRON_SECRET` | Yes, for HTTP cron | Shared secret; caller sends header `X-Renewal-Email-Cron-Secret` with this value |
| `RENEWAL_EMAIL_DRY_RUN` | Optional | If `true` / `1`, logs only; no Resend calls and no send-log rows |
| `RENEWAL_EMAIL_TEST_WHITELIST` | Optional, testing only | Comma-separated recipient emails; when set, only these addresses receive renewal emails |
| `RENEWAL_EMAIL_SEED_TENANT_ID` | Optional | Used by the seed script when `--tenant-id` is omitted |
| `RENEWAL_EMAIL_CRON_TENANT_ID` | Optional | Tenant id used by the daily 8am UK scheduler when `--tenant-id` is omitted |
| `RENEWAL_EMAIL_ADVISOR_NAME_OVERRIDE` | Optional, demo only | Forces every email to show one advisor name; remove/empty for live real advisor names |
| `RENEWAL_EMAIL_DEBUG` | Optional | `1` / `true`: verbose renewal email logs |

## Daily schedule

Production should run the renewal check once per day at **08:00 UK time** (`Europe/London`). That timezone automatically follows GMT/BST.

The send log prevents duplicate emails for the same contract and bucket, so a daily check is safe: contracts only send when they first become eligible for a bucket that has not already been logged.

### Option A: Daily 8am UK worker

Run this as a separate background worker/process on the live server:

```bash
cd cash2switch-backend
python -m backend.scripts.run_renewal_emails_daily_8am_uk --tenant-id YOUR_TENANT_ID
```

For the current tenant 2 setup:

```bash
python -m backend.scripts.run_renewal_emails_daily_8am_uk --tenant-id 2
```

To test the worker command immediately without waiting until 8am:

```bash
python -m backend.scripts.run_renewal_emails_daily_8am_uk --tenant-id 2 --run-once-now --dry-run
```

For live sending, do not pass `--dry-run`, and make sure:

- `RENEWAL_EMAIL_DRY_RUN=false`
- `RENEWAL_EMAIL_TEST_WHITELIST` is empty or removed
- `RESEND_API_KEY` is set
- `RENEWAL_EMAIL_FROM` uses the verified sender domain
- `RENEWAL_EMAIL_ADVISOR_NAME_OVERRIDE` is empty or removed unless one fixed advisor name is intended for every email

The worker logs the next run in both UK time and UTC. During British Summer Time, 08:00 UK is 07:00 UTC. During GMT, 08:00 UK is 08:00 UTC.

### Option B: HTTP cron

`POST https://<your-backend-host>/internal/cron/renewal-emails`

Header: `X-Renewal-Email-Cron-Secret: <same as RENEWAL_EMAIL_CRON_SECRET>`

Optional JSON body: `{"tenant_id": 2}` for a single-tenant run.

If `RENEWAL_EMAIL_CRON_SECRET` is unset, the endpoint returns `503` and stays disabled.

Schedule the HTTP cron provider for **08:00 Europe/London**.

### Option C: CLI manual run

From the `cash2switch-backend` directory with `.env` present:

```bash
python -m backend.scripts.run_renewal_emails --tenant-id 2 --dry-run
python -m backend.scripts.run_renewal_emails --tenant-id 2
```

## Buckets

Buckets are based on days until `contract_end_date`:

- **Under 30 days**: `renewal_under_30`
- **60-90 days**: `renewal_60_90`
- **91-180 days**: `renewal_91_180`

Contracts outside these buckets are not emailed.

## Live checklist

1. Pull/merge the code after resolving any conflicts with latest `main`.
2. Confirm the migration has run on the live database.
3. Set live `.env` values for `DATABASE_URL`, `RESEND_API_KEY`, and `RENEWAL_EMAIL_FROM`.
4. Remove or empty `RENEWAL_EMAIL_TEST_WHITELIST`.
5. Remove or empty `RENEWAL_EMAIL_ADVISOR_NAME_OVERRIDE` unless the business wants one fixed advisor name.
6. Run `python -m backend.scripts.run_renewal_emails --tenant-id 2 --dry-run`.
7. Start the 8am UK worker or configure an external HTTP cron for 08:00 Europe/London.
