-- Client update: all BGB/BGB Lite/British Gas supplier variants should generate
-- yearly commission payment rows. The 80% value is retained for reporting/config,
-- while annual schedule generation uses yearly rows.

WITH supplier_names AS (
  SELECT
    supplier_id,
    regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') AS normalized_name
  FROM "StreemLyne_MT"."Supplier_Master"
)
UPDATE "StreemLyne_MT"."Supplier_Master" AS supplier
SET
  commission_payment_type = 'annual',
  upfront_percentage = 80.00,
  reconciliation_required = FALSE,
  invoice_delay_days = NULL,
  customer_payment_days = NULL,
  grace_days = NULL,
  commission_payment_frequency = 'annual',
  commission_payment_delay_days = 0,
  multi_year_commission_payment_mode = 'annual'
FROM supplier_names
WHERE supplier.supplier_id = supplier_names.supplier_id
  AND (
    supplier_names.normalized_name = 'bgb'
    OR supplier_names.normalized_name LIKE 'bgblite%'
    OR supplier_names.normalized_name LIKE 'britishgasbusiness%'
    OR supplier_names.normalized_name LIKE 'britishgas%'
  );
