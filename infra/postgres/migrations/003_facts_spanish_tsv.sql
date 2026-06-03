-- Waseller — switch facts.content_tsv from 'simple' to 'spanish' config
-- Run once per database. Idempotent (the DROP is safe even on fresh installs
-- because 001 created the same-named column; the ADD re-creates it with
-- 'spanish' stemming + Spanish stop-word removal).
--
-- Why: 'simple' has no stemming. A buyer asking "aceptan tarjeta?" did not
-- match a catalog fact saying "aceptamos tarjeta" — the verb conjugations
-- tokenized to different lexemes. With 'spanish', both stem to `acept`, the
-- match fires, and the agent quotes the right policy instead of hallucinating.
--
-- Tradeoff: 'spanish' also stems product names (Pegasus → 'pegas'), but those
-- are still distinctive enough to match in practice, and the gain on natural
-- language Spanish queries is large.

ALTER TABLE facts DROP COLUMN IF EXISTS content_tsv;
ALTER TABLE facts ADD COLUMN content_tsv
    tsvector GENERATED ALWAYS AS (to_tsvector('spanish', content)) STORED;

-- The GIN index lived on the old column; the DROP removed it. Recreate it.
CREATE INDEX IF NOT EXISTS ix_facts_content_tsv ON facts USING GIN (content_tsv);
