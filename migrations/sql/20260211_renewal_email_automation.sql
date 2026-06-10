-- =============================================================================
-- Renewal customer email automation — PostgreSQL
-- Schema: StreemLyne_MT
-- =============================================================================
-- Creates audit / idempotency table for automated renewal reminder emails.
-- Safe to run once; uses IF NOT EXISTS.
--
-- Example (psql):
--   psql "$DATABASE_URL" -f migrations/sql/20260211_renewal_email_automation.sql
-- =============================================================================

CREATE TABLE IF NOT EXISTS "StreemLyne_MT"."Renewal_Email_Send_Log" (
  renewal_email_send_log_id BIGSERIAL PRIMARY KEY,
  tenant_id SMALLINT NOT NULL,
  energy_contract_master_id SMALLINT NOT NULL,
  contract_end_date DATE NOT NULL,
  bucket_key VARCHAR(50) NOT NULL,
  recipient_email VARCHAR(255) NOT NULL,
  provider_message_id VARCHAR(255),
  status VARCHAR(50) NOT NULL,
  error_message TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  CONSTRAINT uq_renewal_email_send_dedup UNIQUE (
    tenant_id,
    energy_contract_master_id,
    contract_end_date,
    bucket_key
  )
);

CREATE INDEX IF NOT EXISTS ix_renewal_email_send_log_tenant_created
  ON "StreemLyne_MT"."Renewal_Email_Send_Log" (tenant_id, created_at DESC);
