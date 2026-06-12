-- Waseller — agnostic data layer: resources + data_sources + query_log
-- Run once per database. Idempotent.
--
-- Why this exists: PR #35 introduces a vertical-agnostic data model. Instead
-- of hard-coding tables per vertical (properties, products, services), the
-- agent searches over ``resources`` — a JSONB-backed store where each row
-- has whatever shape the data source feeds. A real estate inmo writes rows
-- with {neighborhood, price, bedrooms}; an e-commerce shop writes {sku,
-- price, stock}; the same agent skill ``resource-search`` filters both.
--
-- The schema EMERGES from usage:
--  * ``data`` JSONB stores whatever fields the source has
--  * ``query_log`` tracks every filter the agent actually used
--  * future PR #40 uses that log to enrich the SOUL prompt with the
--    "fields most asked about" so the agent learns to surface them.

-- -----------------------------------------------------------------------------
-- data_sources — where the resources come from (HTML, JSON API, webhook, ...)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS data_sources (
    id              TEXT        PRIMARY KEY,
    tenant_id       TEXT        NOT NULL,
    -- 'html', 'json_api', 'webhook', 'manual', 'csv', ...
    kind            TEXT        NOT NULL,
    name            TEXT        NOT NULL,
    -- Adapter-specific config. HtmlScraperDataSource reads {url, item_selector,
    -- field_selectors}; JsonApiDataSource reads {url, headers, json_path}.
    -- Webhook only needs {secret}. Future adapters define their own.
    config          JSONB       NOT NULL DEFAULT '{}'::jsonb,
    last_synced_at  TIMESTAMPTZ,
    last_sync_ok    BOOLEAN,
    last_sync_count INTEGER,
    last_sync_error TEXT,
    status          TEXT        NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_data_sources_tenant
    ON data_sources (tenant_id, kind);

-- -----------------------------------------------------------------------------
-- resources — the actual items the agent searches
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS resources (
    id              TEXT        PRIMARY KEY,
    tenant_id       TEXT        NOT NULL,
    -- NULL when inserted manually (no source). Otherwise the source that
    -- fed this resource — used to dedup on (source_id, external_id) and
    -- to delete-cascade when the source goes away.
    source_id       TEXT        REFERENCES data_sources (id) ON DELETE SET NULL,
    -- Caller-defined: 'property', 'product', 'service', 'item', ...
    -- Lets one tenant mix verticals (a real-estate inmo with rental
    -- properties + sale properties + ancillary services in one store).
    kind            TEXT        NOT NULL DEFAULT 'item',
    -- ID from the upstream source (e.g. inmo's internal property ID). The
    -- (tenant_id, source_id, external_id) tuple is the dedup key on sync.
    external_id     TEXT,
    -- The actual data — completely schema-less. Whatever the source feeds.
    data            JSONB       NOT NULL DEFAULT '{}'::jsonb,
    -- Short text the agent can quote without dumping the full JSONB.
    -- Defaults to the data's "title" or "name" if either exists; the
    -- application sets it explicitly when the source knows better.
    summary         TEXT,
    -- 'active' = searchable, 'archived' = excluded but kept for history.
    status          TEXT        NOT NULL DEFAULT 'active',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- One row per (source, external_id) — re-syncing the same item updates
    -- in place instead of duplicating. external_id can be NULL for manual
    -- inserts; the UNIQUE only fires when both columns are non-null because
    -- of how PostgreSQL handles NULL uniqueness.
    UNIQUE (tenant_id, source_id, external_id)
);

CREATE INDEX IF NOT EXISTS ix_resources_tenant_kind
    ON resources (tenant_id, kind, status);

-- Full-text search on summary + a flattened text view of the JSONB so the
-- agent can query like "2 ambientes Belgrano" and tsquery matches against
-- whatever field names the source happened to use.
CREATE INDEX IF NOT EXISTS ix_resources_search_tsv
    ON resources USING gin (
        (setweight(to_tsvector('spanish', coalesce(summary, '')), 'A') ||
         setweight(to_tsvector('spanish', coalesce(data::text, '')), 'B'))
    );

-- jsonb_path_ops GIN index supports @>, ?, ?& and ?| containment / key
-- presence queries — what ResourceSearchSkill uses for the structured
-- filter half ({neighborhood: "Belgrano"} → data @> '{"neighborhood":"Belgrano"}').
CREATE INDEX IF NOT EXISTS ix_resources_data
    ON resources USING gin (data jsonb_path_ops);

-- -----------------------------------------------------------------------------
-- query_log — every filter + query the agent ran (basis for the learning loop)
-- -----------------------------------------------------------------------------

CREATE TABLE IF NOT EXISTS resource_query_log (
    id              BIGSERIAL   PRIMARY KEY,
    tenant_id       TEXT        NOT NULL,
    buyer_id        TEXT,
    -- Free-text part of the query (the buyer's message, or extracted intent).
    query_text      TEXT,
    -- Structured filters the skill actually applied. Future PR #40 reads
    -- the most-used keys here to enrich the SOUL prompt with "the fields
    -- buyers most often ask about are: X, Y, Z".
    filters         JSONB       NOT NULL DEFAULT '{}'::jsonb,
    result_count    INTEGER     NOT NULL DEFAULT 0,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_resource_query_log_tenant_recent
    ON resource_query_log (tenant_id, created_at DESC);
