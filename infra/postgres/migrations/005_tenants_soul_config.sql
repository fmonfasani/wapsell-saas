-- Waseller — add soul_config column to tenants
-- Run once per database. Idempotent.
--
-- Why this exists: SOUL is the agent's behavioral prompt (language, tone,
-- mission, rules). Until now it lived only as Python-side defaults, which
-- meant every tenant got the same prompt and customization required a code
-- change. PR #19 added a per-tenant SoulConfig that the dashboard SOUL
-- editor writes to via PUT /tenants/{id}/soul. NULL means "use the SDK
-- defaults" — the row stays valid for tenants created before this column
-- existed without a backfill.

ALTER TABLE tenants
    ADD COLUMN IF NOT EXISTS soul_config JSONB;
