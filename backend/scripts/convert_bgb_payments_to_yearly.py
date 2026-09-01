from __future__ import annotations

from sqlalchemy import text

from backend.db import engine


CONVERSION_SQL = """
BEGIN;
SET LOCAL statement_timeout = 0;

CREATE TEMP TABLE tmp_bgb_suppliers AS
SELECT supplier_id
FROM "StreemLyne_MT"."Supplier_Master"
WHERE regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') = 'bgb'
   OR regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') LIKE 'bgblite%'
   OR regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') LIKE 'britishgasbusiness%'
   OR regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') LIKE 'britishgas%';

CREATE TEMP TABLE tmp_bgb_contracts AS
SELECT DISTINCT contract_id
FROM "StreemLyne_MT"."Commission_Payment"
WHERE supplier_id IN (SELECT supplier_id FROM tmp_bgb_suppliers)
  AND payment_policy_type IN ('monthly_actual', 'upfront_reconciliation', 'upfront')
  AND contract_id IS NOT NULL
  AND NOT EXISTS (
    SELECT 1
    FROM "StreemLyne_MT"."Commission_Payment_Receipt" receipt
    JOIN "StreemLyne_MT"."Commission_Payment" receipt_payment
      ON receipt_payment.id = receipt.commission_payment_id
    WHERE receipt_payment.contract_id = "Commission_Payment".contract_id
      AND receipt_payment.supplier_id IN (SELECT supplier_id FROM tmp_bgb_suppliers)
  );

CREATE TEMP TABLE tmp_old_bgb_payments AS
SELECT
  cp.*,
  GREATEST(((cp.instalment_year - 1) / 12)::integer + 1, 1) AS yearly_instalment
FROM "StreemLyne_MT"."Commission_Payment" cp
WHERE cp.contract_id IN (SELECT contract_id FROM tmp_bgb_contracts)
  AND cp.supplier_id IN (SELECT supplier_id FROM tmp_bgb_suppliers);

CREATE TEMP TABLE tmp_bgb_yearly_groups AS
SELECT
  MIN(id) AS keeper_id,
  tenant_id,
  client_id,
  project_id,
  contract_id,
  supplier_id,
  employee_id,
  yearly_instalment AS instalment_year,
  GREATEST(MIN(payment_period_start), DATE '2022-01-01') AS payment_period_start,
  MAX(payment_period_end) AS payment_period_end,
  aggregator,
  MAX(annual_usage) AS annual_usage,
  MAX(uplift) AS uplift,
  MAX(contract_term_years) AS contract_term_years,
  MIN(live_date) AS live_date,
  SUM(expected_gross_amount) AS expected_gross_amount,
  SUM(expected_net_amount) AS expected_net_amount,
  MIN(GREATEST(COALESCE(due_date, payment_period_start), DATE '2022-01-01')) AS due_date,
  MIN(created_at) AS created_at
FROM tmp_old_bgb_payments
WHERE COALESCE(due_date, payment_period_start) >= DATE '2022-01-01'
GROUP BY
  tenant_id,
  client_id,
  project_id,
  contract_id,
  supplier_id,
  employee_id,
  yearly_instalment,
  aggregator;

UPDATE "StreemLyne_MT"."Commission_Payment_Receipt" receipt
SET commission_payment_id = yearly.keeper_id
FROM tmp_old_bgb_payments old_payment
JOIN tmp_bgb_yearly_groups yearly
  ON yearly.contract_id = old_payment.contract_id
 AND yearly.instalment_year = old_payment.yearly_instalment
WHERE receipt.commission_payment_id = old_payment.id
  AND receipt.commission_payment_id <> yearly.keeper_id;

DELETE FROM "StreemLyne_MT"."Commission_Payment" payment
USING tmp_old_bgb_payments old_payment
LEFT JOIN tmp_bgb_yearly_groups yearly ON yearly.keeper_id = old_payment.id
WHERE payment.id = old_payment.id
  AND yearly.keeper_id IS NULL;

UPDATE "StreemLyne_MT"."Commission_Payment" payment
SET
  tenant_id = yearly.tenant_id,
  client_id = yearly.client_id,
  project_id = yearly.project_id,
  contract_id = yearly.contract_id,
  supplier_id = yearly.supplier_id,
  employee_id = yearly.employee_id,
  instalment_year = yearly.instalment_year,
  payment_policy_type = 'annual',
  payment_period_label = ('Year ' || yearly.instalment_year),
  payment_period_start = yearly.payment_period_start,
  payment_period_end = yearly.payment_period_end,
  aggregator = yearly.aggregator,
  annual_usage = yearly.annual_usage,
  uplift = yearly.uplift,
  contract_term_years = yearly.contract_term_years,
  live_date = yearly.live_date,
  expected_gross_amount = yearly.expected_gross_amount,
  expected_net_amount = yearly.expected_net_amount,
  due_date = yearly.due_date,
  amount_received = 0,
  outstanding_amount = yearly.expected_net_amount,
  status = CASE WHEN yearly.instalment_year = 1 THEN 'Pending' ELSE 'Scheduled' END,
  last_checked_at = NULL,
  next_follow_up_date = NULL,
  follow_up_count = 0,
  updated_at = NOW()
FROM tmp_bgb_yearly_groups yearly
WHERE payment.id = yearly.keeper_id;

UPDATE "StreemLyne_MT"."Commission_Payment" payment
SET
  amount_received = receipt_totals.total_received,
  outstanding_amount = GREATEST(payment.expected_net_amount - receipt_totals.total_received, 0),
  status = CASE
    WHEN GREATEST(payment.expected_net_amount - receipt_totals.total_received, 0) = 0 THEN 'Received'
    ELSE 'Partially Paid'
  END,
  last_checked_at = NOW(),
  updated_at = NOW()
FROM (
  SELECT commission_payment_id, COALESCE(SUM(amount_received), 0) AS total_received
  FROM "StreemLyne_MT"."Commission_Payment_Receipt"
  WHERE commission_payment_id IN (SELECT keeper_id FROM tmp_bgb_yearly_groups)
  GROUP BY commission_payment_id
) receipt_totals
WHERE payment.id = receipt_totals.commission_payment_id;

COMMIT;
"""


VERIFY_SQL = """
WITH bgb_suppliers AS (
  SELECT supplier_id, supplier_company_name
  FROM "StreemLyne_MT"."Supplier_Master"
  WHERE regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') = 'bgb'
     OR regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') LIKE 'bgblite%'
     OR regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') LIKE 'britishgasbusiness%'
     OR regexp_replace(lower(coalesce(supplier_company_name, '')), '[^a-z0-9]+', '', 'g') LIKE 'britishgas%'
)
SELECT
  supplier.supplier_company_name,
  supplier.commission_payment_type,
  supplier.upfront_percentage,
  supplier.commission_payment_frequency,
  supplier.multi_year_commission_payment_mode,
  payment.payment_policy_type,
  COUNT(payment.id) AS payment_rows,
  COUNT(receipt.id) AS receipt_rows,
  MIN(payment.payment_period_start) AS min_period_start,
  MAX(payment.payment_period_end) AS max_period_end
FROM bgb_suppliers bgb
JOIN "StreemLyne_MT"."Supplier_Master" supplier ON supplier.supplier_id = bgb.supplier_id
LEFT JOIN "StreemLyne_MT"."Commission_Payment" payment ON payment.supplier_id = supplier.supplier_id
LEFT JOIN "StreemLyne_MT"."Commission_Payment_Receipt" receipt ON receipt.commission_payment_id = payment.id
GROUP BY
  supplier.supplier_company_name,
  supplier.commission_payment_type,
  supplier.upfront_percentage,
  supplier.commission_payment_frequency,
  supplier.multi_year_commission_payment_mode,
  payment.payment_policy_type
ORDER BY supplier.supplier_company_name, payment.payment_policy_type;
"""


def main() -> None:
    with engine.connect() as conn:
        conn.execute(text(CONVERSION_SQL))
        rows = conn.execute(text(VERIFY_SQL)).mappings().all()
        for row in rows:
            print(dict(row))


if __name__ == "__main__":
    main()
