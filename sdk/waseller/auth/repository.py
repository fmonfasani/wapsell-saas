"""User + Session persistence ports + in-memory / Postgres adapters."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol, runtime_checkable

from waseller.models import Session, User, UserRole


@runtime_checkable
class UserRepositoryPort(Protocol):
    def add(self, user: User) -> User: ...
    def get(self, user_id: str) -> User | None: ...
    def by_email(self, email: str) -> User | None: ...
    def list_all(self) -> list[User]: ...


@runtime_checkable
class SessionRepositoryPort(Protocol):
    def add(self, session: Session) -> Session: ...
    def get(self, token: str) -> Session | None: ...
    def delete(self, token: str) -> bool: ...


# ---------------------------------------------------------------------------
# In-memory adapters
# ---------------------------------------------------------------------------


@dataclass(slots=True)
class InMemoryUserRepository:
    _by_id: dict[str, User] = field(default_factory=dict)

    def add(self, user: User) -> User:
        for existing in self._by_id.values():
            if existing.email.lower() == user.email.lower():
                raise ValueError(f"email already exists: {user.email}")
        self._by_id[user.id] = user
        return user

    def get(self, user_id: str) -> User | None:
        return self._by_id.get(user_id)

    def by_email(self, email: str) -> User | None:
        e = email.lower()
        return next((u for u in self._by_id.values() if u.email.lower() == e), None)

    def list_all(self) -> list[User]:
        return list(self._by_id.values())


@dataclass(slots=True)
class InMemorySessionRepository:
    _by_token: dict[str, Session] = field(default_factory=dict)

    def add(self, session: Session) -> Session:
        self._by_token[session.token] = session
        return session

    def get(self, token: str) -> Session | None:
        return self._by_token.get(token)

    def delete(self, token: str) -> bool:
        return self._by_token.pop(token, None) is not None


# ---------------------------------------------------------------------------
# Postgres adapters
# ---------------------------------------------------------------------------


_USER_COLS = "id, email, password_hash, role, tenant_id, created_at"
_USER_INSERT_SQL = f"INSERT INTO users ({_USER_COLS}) VALUES (%s, %s, %s, %s, %s, %s)"  # noqa: S608
_USER_BY_ID_SQL = f"SELECT {_USER_COLS} FROM users WHERE id = %s"  # noqa: S608
_USER_BY_EMAIL_SQL = f"SELECT {_USER_COLS} FROM users WHERE LOWER(email) = LOWER(%s)"  # noqa: S608
_USER_LIST_ALL_SQL = f"SELECT {_USER_COLS} FROM users ORDER BY created_at"  # noqa: S608


class PostgresUserRepository:
    """Postgres-backed user store. The email uniqueness is enforced by both
    a DB UNIQUE constraint (clean SQL error → ValueError) and a pre-check
    on add to surface the conflict before the INSERT runs."""

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API
        self._conn = connection

    def add(self, user: User) -> User:
        if self.by_email(user.email) is not None:
            raise ValueError(f"email already exists: {user.email}")
        with self._conn.cursor() as cur:
            cur.execute(
                _USER_INSERT_SQL,
                (
                    user.id,
                    user.email,
                    user.password_hash,
                    user.role.value,
                    user.tenant_id,
                    user.created_at,
                ),
            )
        self._conn.commit()
        return user

    def get(self, user_id: str) -> User | None:
        with self._conn.cursor() as cur:
            cur.execute(_USER_BY_ID_SQL, (user_id,))
            rows = cur.fetchall()
        return self._row_to_user(rows[0]) if rows else None

    def by_email(self, email: str) -> User | None:
        with self._conn.cursor() as cur:
            cur.execute(_USER_BY_EMAIL_SQL, (email,))
            rows = cur.fetchall()
        return self._row_to_user(rows[0]) if rows else None

    def list_all(self) -> list[User]:
        with self._conn.cursor() as cur:
            cur.execute(_USER_LIST_ALL_SQL, ())
            rows = cur.fetchall()
        return [self._row_to_user(row) for row in rows]

    @staticmethod
    def _row_to_user(row: Any) -> User:  # noqa: ANN401 — DB-API row tuple
        # row: (id, email, password_hash, role, tenant_id, created_at)
        created = row[5]
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        return User(
            id=row[0],
            email=row[1],
            password_hash=row[2],
            role=UserRole(row[3]),
            tenant_id=row[4],
            created_at=created,
        )


_SESSION_INSERT_SQL = (
    "INSERT INTO sessions (token, user_id, expires_at, created_at) VALUES (%s, %s, %s, %s)"
)
# The "token" word inside this constant name makes ruff S105 fire — it's a
# SQL statement, not a credential. The comment is intentionally phrased to
# not contain the "noqa" keyword so RUF100 doesn't see a directive on it.
_SESSION_BY_TOKEN_SQL = (
    "SELECT token, user_id, expires_at, created_at FROM sessions WHERE token = %s"  # noqa: S105
)
_SESSION_DELETE_SQL = "DELETE FROM sessions WHERE token = %s"


class PostgresSessionRepository:
    """Postgres-backed sessions. Expired rows are NOT auto-deleted here — the
    AuthService refuses to authenticate them, and a periodic cleanup job
    (out of scope for this PR) eventually GCs the table."""

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API
        self._conn = connection

    def add(self, session: Session) -> Session:
        with self._conn.cursor() as cur:
            cur.execute(
                _SESSION_INSERT_SQL,
                (session.token, session.user_id, session.expires_at, session.created_at),
            )
        self._conn.commit()
        return session

    def get(self, token: str) -> Session | None:
        with self._conn.cursor() as cur:
            cur.execute(_SESSION_BY_TOKEN_SQL, (token,))
            rows = cur.fetchall()
        if not rows:
            return None
        row = rows[0]
        expires = row[2]
        created = row[3]
        if isinstance(expires, str):
            expires = datetime.fromisoformat(expires)
        if isinstance(created, str):
            created = datetime.fromisoformat(created)
        return Session(
            token=row[0],
            user_id=row[1],
            expires_at=expires,
            created_at=created,
        )

    def delete(self, token: str) -> bool:
        with self._conn.cursor() as cur:
            cur.execute(_SESSION_BY_TOKEN_SQL, (token,))
            if not cur.fetchall():
                return False
            cur.execute(_SESSION_DELETE_SQL, (token,))
        self._conn.commit()
        return True
