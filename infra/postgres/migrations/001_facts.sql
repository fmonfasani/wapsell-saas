-- Waseller — facts table (Hindsight RAG)
-- Run once per database. Idempotent.

CREATE TABLE IF NOT EXISTS facts (
    id          TEXT        PRIMARY KEY,
    tenant_id   TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    content     TEXT        NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Materialized tsvector for fast lexical search. 'spanish' applies stemming
    -- so "aceptamos" and "aceptan" both stem to 'acept' and match buyer queries
    -- regardless of conjugation. Stop words ("para", "en", "que", ...) are also
    -- filtered, which keeps the AND/OR matching focused on meaningful tokens.
    -- For an English-only tenant swap to 'english'; for raw substring matching
    -- (no stemming, useful for SKU codes) use 'simple'. PR #15 default = spanish.
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED
);

-- Tenant scoping is on every query; this index is mandatory.
CREATE INDEX IF NOT EXISTS ix_facts_tenant       ON facts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_facts_created      ON facts (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_facts_content_tsv  ON facts USING GIN (content_tsv);
