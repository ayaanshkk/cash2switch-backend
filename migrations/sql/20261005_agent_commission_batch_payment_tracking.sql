-- Add payment tracking fields to Agent_Commission_Batch
-- Allows logging partial/full commission payments to agents with notes

ALTER TABLE "StreemLyne_MT"."Agent_Commission_Batch"
    ADD COLUMN IF NOT EXISTS amount_paid    NUMERIC(14, 2) NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS payment_notes  TEXT,
    ADD COLUMN IF NOT EXISTS payment_date   DATE,
    ADD COLUMN IF NOT EXISTS payment_log    JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Expand status to allow Partially Paid
ALTER TABLE "StreemLyne_MT"."Agent_Commission_Batch"
    DROP CONSTRAINT IF EXISTS ck_agent_commission_batch_status;

ALTER TABLE "StreemLyne_MT"."Agent_Commission_Batch"
    ADD CONSTRAINT ck_agent_commission_batch_status
    CHECK (status IN ('Awaiting Payment', 'Partially Paid', 'Commission Paid'));
