-- Waseller — billing: Mercado Pago subscriptions (PR #47).
-- Run once per database. Idempotent.
--
-- Why this exists: every tenant pays via MP Preapproval (recurring). We
-- mirror the MP-side preapproval lifecycle here so the dashboard and
-- feature-gating can answer "is this tenant paying right now?" without
-- hitting the MP API on every request.
--
-- Schema notes:
--  * ``mp_preapproval_id`` is UNIQUE because MP's id is the dedup key
--    across the entire system; we never want two local rows pointing
--    at the same MP-side subscription.
--  * We DON'T put a UNIQUE on (tenant_id, status='authorized') —
--    Postgres can do partial uniques but they bite during MP race
--    conditions (webhook flips A→AUTHORIZED while user is creating B).
--    The BillingService enforces the at-most-one-active invariant in
--    application code instead.
--  * ``status`` mirrors MP's lifecycle: pending → authorized → (paused
--    | cancelled). See SubscriptionStatus in models.py.

CREATE TABLE IF NOT EXISTS subscriptions (
    id                  TEXT        PRIMARY KEY,
    tenant_id           TEXT        NOT NULL,
    plan_code           TEXT        NOT NULL,
    status              TEXT        NOT NULL DEFAULT 'pending',
    mp_preapproval_id   TEXT        UNIQUE,
    mp_init_point       TEXT,
    payer_email         TEXT,
    started_at          TIMESTAMPTZ,
    current_period_end  TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_subscriptions_tenant_status
    ON subscriptions (tenant_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_subscriptions_status
    ON subscriptions (status)
    WHERE status IN ('pending', 'authorized');
