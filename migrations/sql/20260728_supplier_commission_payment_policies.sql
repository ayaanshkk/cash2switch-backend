-- Supplier-specific commission payment policies supplied by the client.
-- Apply to PostgreSQL/Supabase schema: StreemLyne_MT.

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
ADD COLUMN IF NOT EXISTS commission_payment_type VARCHAR(40),
ADD COLUMN IF NOT EXISTS upfront_percentage NUMERIC(5, 2),
ADD COLUMN IF NOT EXISTS reconciliation_required BOOLEAN,
ADD COLUMN IF NOT EXISTS invoice_delay_days INTEGER,
ADD COLUMN IF NOT EXISTS customer_payment_days INTEGER,
ADD COLUMN IF NOT EXISTS grace_days INTEGER,
ADD COLUMN IF NOT EXISTS commission_payment_frequency VARCHAR(20);

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
DROP CONSTRAINT IF EXISTS ck_supplier_commission_payment_type;

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
ADD CONSTRAINT ck_supplier_commission_payment_type CHECK (
  commission_payment_type IS NULL
  OR commission_payment_type IN (
    'annual',
    'upfront_reconciliation',
    'monthly_actual',
    'quarterly_actual'
  )
);

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
DROP CONSTRAINT IF EXISTS ck_supplier_upfront_percentage;

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
ADD CONSTRAINT ck_supplier_upfront_percentage CHECK (
  upfront_percentage IS NULL
  OR (upfront_percentage >= 0 AND upfront_percentage <= 100)
);

ALTER TABLE "StreemLyne_MT"."Commission_Payment"
ADD COLUMN IF NOT EXISTS payment_policy_type VARCHAR(40),
ADD COLUMN IF NOT EXISTS payment_period_label VARCHAR(100),
ADD COLUMN IF NOT EXISTS payment_period_start DATE,
ADD COLUMN IF NOT EXISTS payment_period_end DATE;

-- Normalize punctuation, spaces and underscores so all known CRM spelling variants
-- receive the same client-approved policy.
WITH supplier_names AS (
  SELECT
    supplier_id,
    regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') AS normalized_name
  FROM "StreemLyne_MT"."Supplier_Master"
)
UPDATE "StreemLyne_MT"."Supplier_Master" AS supplier
SET
  commission_payment_type = 'upfront_reconciliation',
  upfront_percentage = 70.00,
  reconciliation_required = TRUE,
  invoice_delay_days = NULL,
  customer_payment_days = NULL,
  grace_days = NULL,
  commission_payment_frequency = 'upfront',
  commission_payment_delay_days = 0,
  multi_year_commission_payment_mode = 'upfront'
FROM supplier_names
WHERE supplier.supplier_id = supplier_names.supplier_id
  AND (
    supplier_names.normalized_name LIKE 'eon%'
    OR supplier_names.normalized_name LIKE 'smartest%'
  );

WITH supplier_names AS (
  SELECT
    supplier_id,
    regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') AS normalized_name
  FROM "StreemLyne_MT"."Supplier_Master"
)
UPDATE "StreemLyne_MT"."Supplier_Master" AS supplier
SET
  commission_payment_type = 'monthly_actual',
  upfront_percentage = NULL,
  reconciliation_required = FALSE,
  invoice_delay_days = 21,
  customer_payment_days = 21,
  grace_days = 2,
  commission_payment_frequency = 'monthly',
  commission_payment_delay_days = 44,
  multi_year_commission_payment_mode = 'annual'
FROM supplier_names
WHERE supplier.supplier_id = supplier_names.supplier_id
  AND (
    supplier_names.normalized_name LIKE '%coronaenergy%'
    OR supplier_names.normalized_name LIKE 'jellyfishenergy%'
    OR supplier_names.normalized_name = 'ygp'
    OR supplier_names.normalized_name LIKE 'yuenergy%'
    OR supplier_names.normalized_name LIKE 'pozitive%'
    OR supplier_names.normalized_name LIKE 'poziitve%'
    OR supplier_names.normalized_name LIKE 'pozitivee%'
    OR supplier_names.normalized_name = 'positiveenergy'
  );

WITH supplier_names AS (
  SELECT
    supplier_id,
    regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') AS normalized_name
  FROM "StreemLyne_MT"."Supplier_Master"
)
UPDATE "StreemLyne_MT"."Supplier_Master" AS supplier
SET
  commission_payment_type = 'quarterly_actual',
  upfront_percentage = NULL,
  reconciliation_required = FALSE,
  invoice_delay_days = 21,
  customer_payment_days = 21,
  grace_days = 2,
  commission_payment_frequency = 'quarterly',
  commission_payment_delay_days = 44,
  multi_year_commission_payment_mode = 'annual'
FROM supplier_names
WHERE supplier.supplier_id = supplier_names.supplier_id
  AND supplier_names.normalized_name IN ('totalenergies', 'totalgasandpower');

-- The client confirmed all remaining suppliers pay monthly based on actual
-- billed and paid usage. Keep the named exceptions above unchanged.
UPDATE "StreemLyne_MT"."Supplier_Master"
SET
  commission_payment_type = 'monthly_actual',
  upfront_percentage = NULL,
  reconciliation_required = FALSE,
  invoice_delay_days = 21,
  customer_payment_days = 21,
  grace_days = 2,
  commission_payment_frequency = 'monthly',
  commission_payment_delay_days = 44,
  multi_year_commission_payment_mode = 'annual'
WHERE commission_payment_type IS NULL;

CREATE INDEX IF NOT EXISTS ix_commission_payment_policy_period
ON "StreemLyne_MT"."Commission_Payment" (payment_policy_type, payment_period_end);
