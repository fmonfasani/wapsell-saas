-- Waseller — users + sessions tables for dashboard auth (PR #23).
-- Run once per database. Idempotent.

CREATE TABLE IF NOT EXISTS users (
    id              TEXT        PRIMARY KEY,
    email           TEXT        NOT NULL,
    password_hash   TEXT        NOT NULL,
    role            TEXT        NOT NULL DEFAULT 'TENANT',
    tenant_id       TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- Email is the login identifier; case-insensitive uniqueness so two users
    -- can't sign up with `Foo@bar.com` and `foo@BAR.com`.
    CONSTRAINT users_email_unique UNIQUE (email)
);

CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email_lower ON users (LOWER(email));

CREATE TABLE IF NOT EXISTS sessions (
    token       TEXT        PRIMARY KEY,
    user_id     TEXT        NOT NULL,
    expires_at  TIMESTAMPTZ NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Hot path: validate-session-on-every-request looks up by token. PRIMARY KEY
-- already gives us the lookup, but a second index on (user_id) lets us
-- "log this user out of every device" cheaply if we ever surface that
-- feature.
CREATE INDEX IF NOT EXISTS ix_sessions_user ON sessions (user_id);

-- Cleanup hint for the periodic GC job (out of scope for this PR but cheap
-- to add the index now). Lets `DELETE WHERE expires_at < now()` run on
-- the index.
CREATE INDEX IF NOT EXISTS ix_sessions_expires ON sessions (expires_at);
