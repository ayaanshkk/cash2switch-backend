-- Phase 5: Agent commission batches and statement items
-- Apply to Supabase/PostgreSQL schema: StreemLyne_MT

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Agent_Commission_Batch" (
    id VARCHAR(36) PRIMARY KEY,
    tenant_id VARCHAR(50),
    employee_id INTEGER REFERENCES "StreemLyne_MT"."Employee_Master"(employee_id),
    batch_month DATE NOT NULL,
    total_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    status VARCHAR(50) NOT NULL DEFAULT 'Awaiting Payment',
    paid_at TIMESTAMP NULL,
    paid_by INTEGER NULL REFERENCES "StreemLyne_MT"."Employee_Master"(employee_id),
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT ck_agent_commission_batch_status
        CHECK (status IN ('Awaiting Payment', 'Commission Paid')),
    CONSTRAINT uq_agent_commission_batch_tenant_employee_month
        UNIQUE (tenant_id, employee_id, batch_month)
);

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Agent_Commission_Batch_Item" (
    id VARCHAR(36) PRIMARY KEY,
    batch_id VARCHAR(36) NOT NULL REFERENCES "StreemLyne_MT"."Agent_Commission_Batch"(id) ON DELETE CASCADE,
    commission_payment_id VARCHAR(36) NOT NULL REFERENCES "StreemLyne_MT"."Commission_Payment"(id),
    commission_payment_receipt_id VARCHAR(36) NOT NULL REFERENCES "StreemLyne_MT"."Commission_Payment_Receipt"(id),
    client_name VARCHAR(255),
    receipt_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    commission_rate_snapshot NUMERIC(8, 4) NOT NULL DEFAULT 0,
    commission_amount NUMERIC(14, 2) NOT NULL DEFAULT 0,
    created_at TIMESTAMP NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_agent_commission_batch_item_receipt
        UNIQUE (commission_payment_receipt_id)
);

CREATE INDEX IF NOT EXISTS idx_agent_commission_batch_tenant_month
    ON "StreemLyne_MT"."Agent_Commission_Batch" (tenant_id, batch_month);

CREATE INDEX IF NOT EXISTS idx_agent_commission_batch_employee
    ON "StreemLyne_MT"."Agent_Commission_Batch" (employee_id);

CREATE INDEX IF NOT EXISTS idx_agent_commission_batch_item_batch
    ON "StreemLyne_MT"."Agent_Commission_Batch_Item" (batch_id);
