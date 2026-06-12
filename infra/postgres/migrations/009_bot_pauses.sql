-- Waseller — bot pause registry (PostgresBotPauseRepository)
-- Run once per database. Idempotent.
--
-- Why this exists: PR #26 lets human agents grab a thread from the bot.
-- When that happens, the agent loop must skip the LLM call for inbound
-- messages on that buyer until the pause expires or a human resumes.
-- One row per (tenant_id, buyer_id) pair; UPSERT semantics on pause so
-- extending or shortening a window is a single statement.

CREATE TABLE IF NOT EXISTS bot_pauses (
    tenant_id    TEXT        NOT NULL,
    buyer_id     TEXT        NOT NULL,
    paused_until TIMESTAMPTZ NOT NULL,
    PRIMARY KEY (tenant_id, buyer_id)
);

-- is_paused runs on every inbound webhook — index the (tenant_id, buyer_id,
-- paused_until) tuple so the planner can answer "is there a row for this
-- pair with paused_until > $1" with an index-only scan.
--
-- Note: the original draft used a partial index `WHERE paused_until > now()`
-- but Postgres rejects that ("functions in index predicate must be marked
-- IMMUTABLE") because now() is volatile. The full index is slightly larger
-- but functionally equivalent for our workload — expired rows are GC'd
-- lazily on re-pause UPSERTs, so the index won't grow unbounded in practice.
CREATE INDEX IF NOT EXISTS ix_bot_pauses_active
    ON bot_pauses (tenant_id, buyer_id, paused_until);
