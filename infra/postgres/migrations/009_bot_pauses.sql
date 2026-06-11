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

-- is_paused runs on every inbound webhook — narrow partial index so
-- expired pauses don't bloat the lookup. Expired rows are GC'd lazily
-- (left in table until a re-pause UPSERTs over them or a future cron
-- DELETEs them).
CREATE INDEX IF NOT EXISTS ix_bot_pauses_active
    ON bot_pauses (tenant_id, buyer_id, paused_until)
    WHERE paused_until > now();
