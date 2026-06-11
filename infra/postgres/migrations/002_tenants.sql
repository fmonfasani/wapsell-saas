-- Waseller — tenants table (PostgresTenantRepository)
-- Run once per database. Idempotent.
--
-- Why this exists: until this migration runs, the API uses InMemoryTenantRepository,
-- which means tenant state lives in the process and is lost on every restart of
-- the api container (e.g. `docker compose up -d --force-recreate api`). With this
-- table + PostgresTenantRepository wired in main.py, tenants survive restarts and
-- the api can safely scale past --workers 1. See docs/PRODUCTION-LOG.md gotcha #8.

CREATE TABLE IF NOT EXISTS tenants (
    id                        TEXT        PRIMARY KEY,
    name                      TEXT        NOT NULL,
    slug                      TEXT        NOT NULL UNIQUE,
    status                    TEXT        NOT NULL,
    whatsapp_phone_number_id  TEXT,
    model                     TEXT        NOT NULL DEFAULT 'openai/gpt-4o-mini',
    -- Per-tenant SOUL configuration (language/tone/mission/rules). NULL means
    -- "use SDK defaults"; the dashboard SOUL editor writes here via
    -- PUT /tenants/{id}/soul. Migration 005 adds this column to clusters that
    -- predate it; this DDL is for fresh deploys.
    soul_config               JSONB,
    -- Bot → human handoff configuration. NULL means "not configured" and the
    -- agent loop skips the detector entirely. Migration 008 adds this column
    -- to clusters that predate it; this DDL is for fresh deploys.
    handoff_config            JSONB,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Webhook routing path: phone_number_id → tenant lookup, on every inbound message.
-- Partial index so NULL phone_number_ids (provisioning tenants without a number
-- yet) don't bloat the index.
CREATE INDEX IF NOT EXISTS ix_tenants_phone_number_id
    ON tenants (whatsapp_phone_number_id)
    WHERE whatsapp_phone_number_id IS NOT NULL;
