-- HermesSell — facts table (Hindsight RAG)
-- Run once per database. Idempotent.

CREATE TABLE IF NOT EXISTS facts (
    id          TEXT        PRIMARY KEY,
    tenant_id   TEXT        NOT NULL,
    source      TEXT        NOT NULL,
    content     TEXT        NOT NULL,
    metadata    JSONB       NOT NULL DEFAULT '{}'::jsonb,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Materialized tsvector for fast lexical search. 'simple' = no stemming so
    -- multilingual catalogs (Spanish + English + product codes) all index
    -- predictably. Swap to 'spanish' if you want stemming for a single-language tenant.
    content_tsv tsvector GENERATED ALWAYS AS (to_tsvector('simple', content)) STORED
);

-- Tenant scoping is on every query; this index is mandatory.
CREATE INDEX IF NOT EXISTS ix_facts_tenant       ON facts (tenant_id);
CREATE INDEX IF NOT EXISTS ix_facts_created      ON facts (created_at DESC);
CREATE INDEX IF NOT EXISTS ix_facts_content_tsv  ON facts USING GIN (content_tsv);
