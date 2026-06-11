-- Waseller — add handoff_config column to tenants
-- Run once per database. Idempotent.
--
-- Why this exists: PR #25 adds bot → human handoff. When a buyer's message
-- trips the per-tenant detector (explicit ask, configurable keywords), the
-- agent stops generating and replies with a fixed "te paso con un humano"
-- message; optionally a webhook is fired so a human can pick the thread up.
-- NULL means "not configured" — the agent loop skips the detector entirely,
-- so rows created before this column existed stay valid without a backfill.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS handoff_config JSONB;
