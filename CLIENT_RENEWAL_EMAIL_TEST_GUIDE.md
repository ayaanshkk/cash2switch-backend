# Renewal email automation — client testing guide

This guide explains how to test automated renewal reminder emails on the **dev-ali** branch. The database migration has already been applied; you share the same database as the dev team.

---

## What this feature does

1. The CRM reads **contract end dates** for electricity and water customers.
2. A daily job (or manual script) finds contracts ending in **60–365 days**.
3. It sends **one email per reminder stage** (60–90 days, 91–180 days, 181+ days) per contract.
4. Sends are logged so the same reminder is never sent twice for the same contract and stage.

During testing, a **whitelist** ensures only your test inbox receives emails — no real customers are contacted.

---

## Before you start

### 1. Pull the code

```bash
git fetch origin
git checkout dev-ali
git pull origin dev-ali
```

### 2. Python environment

From the `cash2switch-backend` folder, use your existing virtual environment and dependencies (`Flask`, `requests`, `python-dotenv`, etc.).

### 3. Configure `.env`

Add or confirm these variables in `cash2switch-backend/.env`:

```text
DATABASE_URL=...                          # already configured (shared DB)

# Required to actually send emails (Resend — https://resend.com)
RESEND_API_KEY=re_xxxxxxxx
RENEWAL_EMAIL_FROM=Renewals <renewals@yourdomain.com>

# TESTING ONLY — only this inbox receives renewal emails while set
RENEWAL_EMAIL_TEST_WHITELIST=you@yourcompany.com

# Optional: default tenant for seed script if you omit --tenant-id
RENEWAL_EMAIL_SEED_TENANT_ID=1

# Optional: dry-run (log only, no send)
# RENEWAL_EMAIL_DRY_RUN=true

# Optional: verbose logs
# RENEWAL_EMAIL_DEBUG=1
```

**Important**

- `RENEWAL_EMAIL_FROM` must use a domain verified in your Resend account.
- `RENEWAL_EMAIL_TEST_WHITELIST` must match the email used for test customers (see step 4 below).
- **Remove or empty `RENEWAL_EMAIL_TEST_WHITELIST` before production** — otherwise only whitelisted addresses receive mail.

---

## Where fake test customers come from

Test customers are **not** created in the CRM UI. They are created by a **seed script** that inserts rows into the same tables as real customers:

| Table | What gets created |
|-------|-------------------|
| `Client_Master` | One test client, company name starts with `[TEST RENEWAL EMAIL]` |
| `Project_Details` | Four projects (sites) for that client |
| `Energy_Contract_Master` | Four contracts — two electricity, two water |

Each contract’s **end date is set to 75 days from today**, which falls in the **60–90 day** reminder bucket (so one test run should send up to **4 emails** to the whitelisted address).

**Script location:** `backend/scripts/seed_renewal_email_test_customers.py`

**Default test email in code:** `ayaans1804@gmail.com` — change `TEST_EMAIL` in that file to your inbox, **or** set the whitelist to match whatever email the seed script uses.

---

## Step-by-step test

All commands are run from the **`cash2switch-backend`** directory.

### Step 1 — Create test customers in the database

Replace `1` with your tenant id if different:

```bash
python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1
```

Preview without writing to the database:

```bash
python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1 --dry-run
```

You should see output like: `Using tenant_id=1, contract_end_date=... (75 days from today)`.

**Verify in CRM (optional):** Search renewals/customers for company names starting with **`[TEST RENEWAL EMAIL]`**.

---

### Step 2 — Dry run (no emails sent)

```bash
python -m backend.scripts.run_renewal_emails --tenant-id 1 --dry-run
```

Expected output example:

```text
{'sent': 0, 'dry_run': 4, 'skipped_dup': 0, 'skipped_bucket': 0, ...}
```

`dry_run: 4` means four test contracts would receive emails.

---

### Step 3 — Send real test emails

Ensure `RESEND_API_KEY`, `RENEWAL_EMAIL_FROM`, and `RENEWAL_EMAIL_TEST_WHITELIST` are set.

```bash
python -m backend.scripts.run_renewal_emails --tenant-id 1
```

Expected output example:

```text
{'sent': 4, 'dry_run': 0, 'skipped_dup': 0, ...}
```

Check the inbox configured in `RENEWAL_EMAIL_TEST_WHITELIST`.

---

### Step 4 — Confirm no duplicate sends

Run the same command again:

```bash
python -m backend.scripts.run_renewal_emails --tenant-id 1
```

Expected:

```text
{'sent': 0, 'skipped_dup': 4, ...}
```

This confirms the system will not spam the same reminder twice.

---

## If nothing sends (`sent: 0`)

Run the diagnostic:

```bash
python -m backend.scripts.diagnose_renewal_emails --tenant-id 1
```

Common fixes:

| Issue | Fix |
|-------|-----|
| Whitelist email ≠ test customer email | Align `RENEWAL_EMAIL_TEST_WHITELIST` with `TEST_EMAIL` in seed script, then re-run seed |
| Resend not configured | Set `RESEND_API_KEY` and `RENEWAL_EMAIL_FROM` |
| Already sent once | `skipped_dup` is expected on second run |
| No seed rows | Re-run `seed_renewal_email_test_customers` |

Enable debug logging:

```bash
set RENEWAL_EMAIL_DEBUG=1
python -m backend.scripts.run_renewal_emails --tenant-id 1
```

(On Mac/Linux use `export RENEWAL_EMAIL_DEBUG=1`.)

---

## Script reference

| Purpose | Command |
|---------|---------|
| Create fake test customers | `python -m backend.scripts.seed_renewal_email_test_customers --tenant-id 1` |
| Send renewal emails (manual) | `python -m backend.scripts.run_renewal_emails --tenant-id 1` |
| Diagnose eligibility | `python -m backend.scripts.diagnose_renewal_emails --tenant-id 1` |

**Code locations**

- Send logic: `backend/services/renewal_email_service.py`
- Email templates: `backend/templates/emails/renewal_reminder.html` and `.txt`
- HTTP cron (production): `POST /internal/cron/renewal-emails` (see `README_RENEWAL_EMAILS.md`)

---

## Cleaning up test data

Test clients are tagged with **`[TEST RENEWAL EMAIL]`** in the company name. When finished testing, delete or archive those clients in the CRM (contracts → projects → client, respecting foreign keys), or ask your dev team to remove them.

---

## Going live (later)

1. Remove or empty `RENEWAL_EMAIL_TEST_WHITELIST`.
2. Schedule `run_renewal_emails` daily (Task Scheduler / cron / HTTP endpoint).
3. Do **not** run the seed script in production.
