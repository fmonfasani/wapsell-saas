-- Waseller — buyer_interactions table (PostgresBuyerMemory)
-- Run once per database. Idempotent.
--
-- Why this exists: until this migration runs, buyer memory uses
-- InMemoryBuyerMemory, which means conversation history is lost on every api
-- container restart (the agent forgets the buyer's name, what product they
-- asked about, the entire context). With this table + PostgresBuyerMemory
-- wired in main.py, conversations survive restarts and the api can scale past
-- --workers 1 without splitting buyer history across workers.

CREATE TABLE IF NOT EXISTS buyer_interactions (
    id          BIGSERIAL    PRIMARY KEY,
    buyer_id    TEXT         NOT NULL,
    role        TEXT         NOT NULL CHECK (role IN ('buyer', 'agent')),
    text        TEXT         NOT NULL,
    metadata    JSONB        NOT NULL DEFAULT '{}'::jsonb,
    at          TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Hot path: recall(buyer_id, limit=N) -> ORDER BY at DESC, id DESC LIMIT N.
-- A composite descending index serves both the limited recall and the trim
-- (which uses the same ORDER BY ... OFFSET pattern) without a sort step.
CREATE INDEX IF NOT EXISTS ix_buyer_interactions_buyer_at
    ON buyer_interactions (buyer_id, at DESC, id DESC);
