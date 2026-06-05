-- Waseller — message_templates table for the dashboard Templates UI.
-- Run once per database. Idempotent.
--
-- WhatsApp Business templates are pre-approved messages a tenant can send
-- *outside* the 24h customer-service window — welcome, order confirmation,
-- abandoned cart, etc. Meta requires they be created, approved, and tied
-- to a WABA before use. This table is the local source of truth; a future
-- PR wires the actual Meta Business Management API.

CREATE TABLE IF NOT EXISTS message_templates (
    id                  TEXT        PRIMARY KEY,
    tenant_id           TEXT        NOT NULL,
    name                TEXT        NOT NULL,
    language            TEXT        NOT NULL DEFAULT 'es_AR',
    category            TEXT        NOT NULL DEFAULT 'UTILITY',
    body                TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'DRAFT',
    vendor_template_id  TEXT,
    rejection_reason    TEXT,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    submitted_at        TIMESTAMPTZ,
    approved_at         TIMESTAMPTZ,

    -- A single tenant can't have two templates with the same (name, language)
    -- pair — Meta enforces this so the dashboard surfaces the conflict early
    -- instead of failing on submit.
    UNIQUE (tenant_id, name, language)
);

-- Listing the tenant's templates is the hot path for the dashboard view.
CREATE INDEX IF NOT EXISTS ix_message_templates_tenant_created
    ON message_templates (tenant_id, created_at DESC);
