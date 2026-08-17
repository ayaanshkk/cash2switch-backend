-- Client update: BGB should not use monthly actual commission terms.
-- BGB pays 80% upfront. Contract length remains per-contract via term_sold
-- or contract_start_date/contract_end_date.

WITH supplier_names AS (
  SELECT
    supplier_id,
    regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') AS normalized_name
  FROM "StreemLyne_MT"."Supplier_Master"
)
UPDATE "StreemLyne_MT"."Supplier_Master" AS supplier
SET
  commission_payment_type = 'upfront_reconciliation',
  upfront_percentage = 80.00,
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
    supplier_names.normalized_name = 'bgb'
    OR supplier_names.normalized_name LIKE 'bgblite%'
    OR supplier_names.normalized_name LIKE 'britishgasbusiness%'
    OR supplier_names.normalized_name LIKE 'britishgas%'
  );
