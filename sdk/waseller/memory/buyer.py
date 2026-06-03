"""Buyer memory — what the agent remembers about each prospect.

Three adapters:

- :class:`InMemoryBuyerMemory` — bounded ring buffer; dev / tests.
- :class:`PostgresBuyerMemory` — PEP 249 connection + ``buyer_interactions``
  table (schema in ``infra/postgres/migrations/004_buyer_interactions.sql``).
  Production default once ``WASELLER_POSTGRES_URL`` is set; survives container
  restarts and is multi-worker safe.
- :class:`HonchoBuyerMemory` — Honcho (Plastic Labs) SDK with its
  ``dialecticDepth`` parameter for synthesized summaries. Drop-in if you want
  Honcho's managed service instead of running your own Postgres.

Tenant scoping is the caller's responsibility: compose ``buyer_id`` as
``"{tenant.slug}:{from_number}"`` so memories from different tenants never collide.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["buyer", "agent"]


@dataclass(frozen=True, slots=True)
class BuyerInteraction:
    """One conversational turn — either side of the chat."""

    text: str
    role: Role = "buyer"
    at: datetime = field(default_factory=lambda: datetime.now(UTC))
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class BuyerMemoryPort(Protocol):
    """Per-buyer conversational store. ``buyer_id`` is opaque to the port."""

    async def remember(self, buyer_id: str, interaction: BuyerInteraction) -> None: ...
    async def recall(
        self, buyer_id: str, *, limit: int | None = None
    ) -> list[BuyerInteraction]: ...
    async def summary(self, buyer_id: str) -> str: ...


@dataclass(slots=True)
class InMemoryBuyerMemory:
    """Bounded in-memory ring buffer. Deterministic; safe in tests.

    ``max_items`` caps the per-buyer history (oldest interactions are dropped
    first). ``dialectic_depth`` is the number of *turn pairs* the synthesized
    summary considers — Honcho's same knob, mirrored here.
    """

    max_items: int = 50
    dialectic_depth: int = 2
    _store: dict[str, list[BuyerInteraction]] = field(default_factory=dict)

    async def remember(self, buyer_id: str, interaction: BuyerInteraction) -> None:
        bucket = self._store.setdefault(buyer_id, [])
        bucket.append(interaction)
        if len(bucket) > self.max_items:
            del bucket[: len(bucket) - self.max_items]

    async def recall(self, buyer_id: str, *, limit: int | None = None) -> list[BuyerInteraction]:
        bucket = self._store.get(buyer_id, [])
        if limit is None:
            return list(bucket)
        if limit <= 0:
            return []
        return list(bucket[-limit:])

    async def summary(self, buyer_id: str) -> str:
        # One turn pair = buyer message + agent reply -> *2 raw interactions.
        recent = await self.recall(buyer_id, limit=self.dialectic_depth * 2)
        if not recent:
            return "no prior interactions"
        return " | ".join(f"[{turn.role}] {turn.text}" for turn in recent)


_BUYER_INSERT_SQL = (
    "INSERT INTO buyer_interactions (buyer_id, role, text, metadata, at) "
    "VALUES (%s, %s, %s, %s::jsonb, %s)"
)
_BUYER_RECALL_ALL_SQL = (
    "SELECT text, role, at, metadata FROM buyer_interactions WHERE buyer_id = %s ORDER BY at, id"
)
# Take the last N rows (DESC + LIMIT) and reorder them ASC for the caller —
# `recall(limit=N)` should return chronological order, not reverse-chrono.
_BUYER_RECALL_LIMITED_SQL = (
    "SELECT text, role, at, metadata FROM ("
    "  SELECT text, role, at, metadata, id "
    "  FROM buyer_interactions WHERE buyer_id = %s "
    "  ORDER BY at DESC, id DESC LIMIT %s"
    ") AS recent ORDER BY at, id"
)
# Mirror InMemoryBuyerMemory's ring-buffer cap: after every insert, prune
# anything beyond the most recent `max_items` rows for this buyer.
_BUYER_TRIM_SQL = (
    "DELETE FROM buyer_interactions WHERE id IN ("
    "  SELECT id FROM buyer_interactions WHERE buyer_id = %s "
    "  ORDER BY at DESC, id DESC OFFSET %s"
    ")"
)


class PostgresBuyerMemory:
    """Postgres-backed buyer memory; PEP 249-compatible connection.

    Mirrors :class:`InMemoryBuyerMemory`'s contract — ``max_items`` caps the
    per-buyer history (oldest pruned), ``dialectic_depth`` controls how many
    turn-pairs the summary considers. The sync DB-API calls are wrapped in
    ``asyncio.to_thread`` so the async port stays non-blocking under
    single-worker uvicorn.

    Schema: ``infra/postgres/migrations/004_buyer_interactions.sql``. Wiring
    this in main.py (via ``WASELLER_POSTGRES_URL``) closes the last in-process
    state that prevented bumping uvicorn workers past 1.
    """

    def __init__(
        self,
        connection: Any,  # noqa: ANN401 — DB-API connection
        *,
        max_items: int = 50,
        dialectic_depth: int = 2,
    ) -> None:
        self._conn = connection
        self._max_items = max_items
        self._dialectic_depth = dialectic_depth

    async def remember(self, buyer_id: str, interaction: BuyerInteraction) -> None:
        await asyncio.to_thread(self._remember_sync, buyer_id, interaction)

    def _remember_sync(self, buyer_id: str, interaction: BuyerInteraction) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                _BUYER_INSERT_SQL,
                (
                    buyer_id,
                    interaction.role,
                    interaction.text,
                    json.dumps(interaction.metadata),
                    interaction.at,
                ),
            )
            cur.execute(_BUYER_TRIM_SQL, (buyer_id, self._max_items))
        self._conn.commit()

    async def recall(self, buyer_id: str, *, limit: int | None = None) -> list[BuyerInteraction]:
        if limit is not None and limit <= 0:
            return []
        return await asyncio.to_thread(self._recall_sync, buyer_id, limit)

    def _recall_sync(self, buyer_id: str, limit: int | None) -> list[BuyerInteraction]:
        with self._conn.cursor() as cur:
            if limit is None:
                cur.execute(_BUYER_RECALL_ALL_SQL, (buyer_id,))
            else:
                cur.execute(_BUYER_RECALL_LIMITED_SQL, (buyer_id, limit))
            rows = cur.fetchall()
        return [self._row_to_interaction(row) for row in rows]

    async def summary(self, buyer_id: str) -> str:
        # One turn pair = buyer message + agent reply -> *2 raw interactions.
        recent = await self.recall(buyer_id, limit=self._dialectic_depth * 2)
        if not recent:
            return "no prior interactions"
        return " | ".join(f"[{turn.role}] {turn.text}" for turn in recent)

    @staticmethod
    def _row_to_interaction(row: Any) -> BuyerInteraction:  # noqa: ANN401 — DB row tuple
        # row: (text, role, at, metadata)
        at_val = row[2]
        if isinstance(at_val, str):
            at_val = datetime.fromisoformat(at_val)
        meta = row[3]
        if isinstance(meta, (str, bytes)):
            meta = json.loads(meta)
        return BuyerInteraction(
            text=row[0],
            role=row[1],
            at=at_val,
            metadata=meta or {},
        )


class HonchoBuyerMemory:
    """Honcho-backed adapter. ``client`` is duck-typed and injected.

    The Honcho SDK surface evolves; this adapter targets the conceptual shape
    (append a message, list messages, request a dialectic summary). When wiring
    the real SDK, reconcile method names without touching :class:`BuyerMemoryPort`
    consumers — that's the point of the port.

    Not exercised in CI: integration tests against a live Honcho instance live
    behind the ``integration`` marker.
    """

    def __init__(
        self,
        client: Any,  # noqa: ANN401 — external SDK boundary
        *,
        namespace: str = "waseller",
        dialectic_depth: int = 2,
    ) -> None:
        self._client = client
        self._namespace = namespace
        self._dialectic_depth = dialectic_depth

    async def remember(self, buyer_id: str, interaction: BuyerInteraction) -> None:
        await self._client.append_message(
            namespace=self._namespace,
            user_id=buyer_id,
            content=interaction.text,
            role=interaction.role,
            metadata=dict(interaction.metadata),
            at=interaction.at.isoformat(),
        )

    async def recall(self, buyer_id: str, *, limit: int | None = None) -> list[BuyerInteraction]:
        raw = await self._client.list_messages(
            namespace=self._namespace, user_id=buyer_id, limit=limit
        )
        return [
            BuyerInteraction(
                text=str(item["content"]),
                role=item.get("role", "buyer"),
                at=_parse_dt(item.get("at")),
                metadata=dict(item.get("metadata") or {}),
            )
            for item in raw
        ]

    async def summary(self, buyer_id: str) -> str:
        result: object = await self._client.dialectic_summary(
            namespace=self._namespace, user_id=buyer_id, depth=self._dialectic_depth
        )
        return str(result)


def _parse_dt(value: object) -> datetime:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        return datetime.fromisoformat(value)
    return datetime.now(UTC)
