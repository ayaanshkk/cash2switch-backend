-- Phase 1: Payment & Commission Management foundation
-- Run against PostgreSQL/Supabase database, schema: StreemLyne_MT.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
ADD COLUMN IF NOT EXISTS commission_payment_delay_days INTEGER,
ADD COLUMN IF NOT EXISTS multi_year_commission_payment_mode VARCHAR(20);

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
DROP CONSTRAINT IF EXISTS ck_supplier_multi_year_commission_payment_mode;

ALTER TABLE "StreemLyne_MT"."Supplier_Master"
ADD CONSTRAINT ck_supplier_multi_year_commission_payment_mode
CHECK (
  multi_year_commission_payment_mode IS NULL
  OR multi_year_commission_payment_mode IN ('annual', 'upfront')
);

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Commission_Payment" (
  id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
  tenant_id VARCHAR(50),
  client_id INTEGER REFERENCES "StreemLyne_MT"."Client_Master"(client_id),
  project_id INTEGER REFERENCES "StreemLyne_MT"."Project_Details"(project_id),
  contract_id INTEGER REFERENCES "StreemLyne_MT"."Energy_Contract_Master"(energy_contract_master_id),
  supplier_id INTEGER REFERENCES "StreemLyne_MT"."Supplier_Master"(supplier_id),
  employee_id INTEGER REFERENCES "StreemLyne_MT"."Employee_Master"(employee_id),
  instalment_year INTEGER NOT NULL,
  aggregator VARCHAR(255),
  annual_usage NUMERIC(14, 2),
  uplift NUMERIC(14, 4),
  contract_term_years INTEGER,
  live_date DATE,
  expected_gross_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
  expected_net_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
  due_date DATE,
  amount_received NUMERIC(14, 2) NOT NULL DEFAULT 0,
  outstanding_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
  status VARCHAR(50) NOT NULL DEFAULT 'Pending',
  last_checked_at TIMESTAMP,
  next_follow_up_date DATE,
  follow_up_count INTEGER NOT NULL DEFAULT 0,
  created_at TIMESTAMP NOT NULL DEFAULT NOW(),
  updated_at TIMESTAMP NOT NULL DEFAULT NOW(),
  CONSTRAINT ck_commission_payment_status CHECK (
    status IN (
      'Scheduled',
      'Pending',
      'Due',
      'Received',
      'Partially Paid',
      'Chasing Supplier',
      'Closed'
    )
  ),
  CONSTRAINT uq_commission_payment_contract_instalment
    UNIQUE (contract_id, instalment_year)
);

CREATE INDEX IF NOT EXISTS ix_commission_payment_tenant_status_due
ON "StreemLyne_MT"."Commission_Payment" (tenant_id, status, due_date);

CREATE INDEX IF NOT EXISTS ix_commission_payment_supplier
ON "StreemLyne_MT"."Commission_Payment" (supplier_id);

CREATE INDEX IF NOT EXISTS ix_commission_payment_employee
ON "StreemLyne_MT"."Commission_Payment" (employee_id);

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Commission_Payment_Receipt" (
  id VARCHAR(36) PRIMARY KEY DEFAULT gen_random_uuid()::text,
  commission_payment_id VARCHAR(36) NOT NULL REFERENCES "StreemLyne_MT"."Commission_Payment"(id) ON DELETE CASCADE,
  tenant_id VARCHAR(50),
  amount_received NUMERIC(14, 2) NOT NULL,
  date_received DATE NOT NULL,
  notes TEXT,
  logged_by INTEGER REFERENCES "StreemLyne_MT"."Employee_Master"(employee_id),
  created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_commission_payment_receipt_payment
ON "StreemLyne_MT"."Commission_Payment_Receipt" (commission_payment_id);

CREATE INDEX IF NOT EXISTS ix_commission_payment_receipt_tenant_date
ON "StreemLyne_MT"."Commission_Payment_Receipt" (tenant_id, date_received);
