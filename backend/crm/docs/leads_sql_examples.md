# CRM Leads — Example SQL (PostgreSQL / Supabase)

This file contains example SQL snippets used by the Leads module. All queries must always be tenant-scoped (filter on `tenant_id`).

## 1) Validate client belongs to tenant
```sql
SELECT "client_id"
FROM "StreemLyne_MT"."Client_Master"
WHERE "client_id" = $1
  AND "tenant_id" = $2
LIMIT 1;
```
Params: (client_id, tenant_id)

---

## 2) Create client + opportunity in one transaction (atomic)
```sql
BEGIN;

-- create client
INSERT INTO "StreemLyne_MT"."Client_Master"
  ("tenant_id", "client_company_name", "client_contact_name", "address", "client_phone", "client_email", "created_at")
VALUES
  ($1, $2, $3, $4, $5, $6, CURRENT_TIMESTAMP)
RETURNING *;

-- create opportunity using returned client_id
INSERT INTO "StreemLyne_MT"."Opportunity_Details"
  ("client_id", "opportunity_title", "opportunity_description", "stage_id", "opportunity_value", "opportunity_owner_employee_id", "created_at")
VALUES
  ($7, $8, $9, $10, $11, $12, CURRENT_TIMESTAMP)
RETURNING *;

COMMIT;
```
Notes: When run from application code use a single DB connection and commit/rollback to ensure atomicity.

---

## 3) Leads list (joined, tenant-scoped)
```sql
SELECT
  od.*,
  cm."client_company_name",
  cm."client_contact_name",
  sm."stage_name",
  em."employee_name" AS assigned_to
FROM "StreemLyne_MT"."Opportunity_Details" od
JOIN "StreemLyne_MT"."Client_Master" cm ON od."client_id" = cm."client_id"
LEFT JOIN "StreemLyne_MT"."Stage_Master" sm ON od."stage_id" = sm."stage_id"
LEFT JOIN "StreemLyne_MT"."Employee_Master" em ON od."opportunity_owner_employee_id" = em."employee_id"
WHERE cm."tenant_id" = $1
ORDER BY od."created_at" DESC
LIMIT 100;
```

---

## 4) Leads table (flat row for UI)
(Same as implemented in repository — uses left joins and subqueries to pull latest interaction and linked project/supplier data.)

---

## 5) Best-practices / security
- Always use parameterised queries; never interpolate `tenant_id` or user input directly into SQL.
- Validate tenant ownership on writes (INSERT/UPDATE/DELETE) by joining into `Client_Master` or filtering by `tenant_id` in the WHERE clause.
- Perform client + lead creation inside a DB transaction to avoid orphaned rows.
- Use appropriate column types and validate numeric ranges (e.g. smallint limits) before inserting.

If you want, I can generate ready-to-run SQL migration snippets or a SQL-only transaction example tailored to your DB schema/version.