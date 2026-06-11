"""Bot-pause persistence — port + in-memory and Postgres adapters.

The contract is small on purpose: the webhook handler asks ``is_paused``
on every inbound message (hot path, must be cheap), the API mutates with
``pause`` / ``resume`` from dashboard actions, and the agent loop's
handoff branch auto-calls ``pause`` when escalation fires.

UPSERT semantics on ``pause``: re-pausing an already-paused buyer extends
or shortens the pause window — last write wins. This is what a human agent
expects: they pause for 8h, mid-shift extend to 24h, the new value sticks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable


@dataclass(frozen=True, slots=True)
class BotPause:
    """One paused (tenant, buyer) pair. ``paused_until`` is timezone-aware
    UTC — comparisons elsewhere assume that and will silently misbehave on
    a naive datetime, so adapters normalize on read."""

    tenant_id: str
    buyer_id: str
    paused_until: datetime


@runtime_checkable
class BotPausePort(Protocol):
    """Persistence boundary for the bot pause registry."""

    def is_paused(self, tenant_id: str, buyer_id: str, *, now: datetime | None = None) -> bool: ...
    def pause(self, tenant_id: str, buyer_id: str, until: datetime) -> BotPause: ...
    def resume(self, tenant_id: str, buyer_id: str) -> None: ...
    def get(self, tenant_id: str, buyer_id: str) -> BotPause | None: ...
    def list_active(self, tenant_id: str, *, now: datetime | None = None) -> list[BotPause]: ...


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(slots=True)
class InMemoryBotPauseRepository:
    """Default adapter. Dict keyed by (tenant_id, buyer_id). Lossy on
    process restart — fine for dev / CI / tests; production uses
    :class:`PostgresBotPauseRepository`."""

    _by_key: dict[tuple[str, str], BotPause] = field(default_factory=dict)

    def is_paused(self, tenant_id: str, buyer_id: str, *, now: datetime | None = None) -> bool:
        pause = self._by_key.get((tenant_id, buyer_id))
        if pause is None:
            return False
        return pause.paused_until > (now or _utcnow())

    def pause(self, tenant_id: str, buyer_id: str, until: datetime) -> BotPause:
        pause = BotPause(tenant_id=tenant_id, buyer_id=buyer_id, paused_until=until)
        self._by_key[(tenant_id, buyer_id)] = pause
        return pause

    def resume(self, tenant_id: str, buyer_id: str) -> None:
        self._by_key.pop((tenant_id, buyer_id), None)

    def get(self, tenant_id: str, buyer_id: str) -> BotPause | None:
        return self._by_key.get((tenant_id, buyer_id))

    def list_active(self, tenant_id: str, *, now: datetime | None = None) -> list[BotPause]:
        cutoff = now or _utcnow()
        return [
            p
            for (tid, _), p in self._by_key.items()
            if tid == tenant_id and p.paused_until > cutoff
        ]


# --- Postgres adapter -------------------------------------------------------

_COLS = "tenant_id, buyer_id, paused_until"

# UPSERT is the safe semantics: re-pausing an already-paused buyer extends
# (or shortens) the window. Composite PK (tenant_id, buyer_id) ensures one
# row per pair; ON CONFLICT DO UPDATE keeps it that way.
_UPSERT_SQL = (
    "INSERT INTO bot_pauses (tenant_id, buyer_id, paused_until) "
    "VALUES (%s, %s, %s) "
    "ON CONFLICT (tenant_id, buyer_id) DO UPDATE "
    "SET paused_until = EXCLUDED.paused_until"
)
_DELETE_SQL = "DELETE FROM bot_pauses WHERE tenant_id = %s AND buyer_id = %s"
_SELECT_ONE_SQL = f"SELECT {_COLS} FROM bot_pauses WHERE tenant_id = %s AND buyer_id = %s"  # noqa: S608
_SELECT_ACTIVE_SQL = (
    f"SELECT {_COLS} FROM bot_pauses "  # noqa: S608
    "WHERE tenant_id = %s AND paused_until > %s "
    "ORDER BY paused_until DESC"
)
# is_paused happens on every inbound webhook; a single existence query is
# cheaper than fetching+comparing the row, and the partial index on
# paused_until keeps the planner happy.
_IS_PAUSED_SQL = (
    "SELECT 1 FROM bot_pauses WHERE tenant_id = %s AND buyer_id = %s AND paused_until > %s"
)


class PostgresBotPauseRepository:
    """Postgres-backed pause registry. PEP 249 connection; schema in
    ``infra/postgres/migrations/009_bot_pauses.sql``."""

    def __init__(self, connection: Any) -> None:  # noqa: ANN401 — DB-API
        self._conn = connection

    def is_paused(self, tenant_id: str, buyer_id: str, *, now: datetime | None = None) -> bool:
        cutoff = now or _utcnow()
        with self._conn.cursor() as cur:
            cur.execute(_IS_PAUSED_SQL, (tenant_id, buyer_id, cutoff))
            return bool(cur.fetchall())

    def pause(self, tenant_id: str, buyer_id: str, until: datetime) -> BotPause:
        with self._conn.cursor() as cur:
            cur.execute(_UPSERT_SQL, (tenant_id, buyer_id, until))
        self._conn.commit()
        return BotPause(tenant_id=tenant_id, buyer_id=buyer_id, paused_until=until)

    def resume(self, tenant_id: str, buyer_id: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(_DELETE_SQL, (tenant_id, buyer_id))
        self._conn.commit()

    def get(self, tenant_id: str, buyer_id: str) -> BotPause | None:
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_ONE_SQL, (tenant_id, buyer_id))
            rows = cur.fetchall()
        return _row_to_pause(rows[0]) if rows else None

    def list_active(self, tenant_id: str, *, now: datetime | None = None) -> list[BotPause]:
        cutoff = now or _utcnow()
        with self._conn.cursor() as cur:
            cur.execute(_SELECT_ACTIVE_SQL, (tenant_id, cutoff))
            rows = cur.fetchall()
        return [_row_to_pause(r) for r in rows]


def _row_to_pause(row: Any) -> BotPause:  # noqa: ANN401 — DB-API row tuple
    paused_until = row[2]
    if isinstance(paused_until, str):
        paused_until = datetime.fromisoformat(paused_until)
    if paused_until.tzinfo is None:
        # psycopg2 sometimes hands back naive datetimes; force UTC so
        # downstream comparisons against _utcnow() are sane.
        paused_until = paused_until.replace(tzinfo=UTC)
    return BotPause(tenant_id=row[0], buyer_id=row[1], paused_until=paused_until)
