"""Buyer memory — what the agent remembers about each prospect.

Honcho (Plastic Labs) is the production backing store with its ``dialecticDepth``
parameter for synthesized summaries. For local dev and tests we use an in-memory
ring buffer; the public ``BuyerMemoryPort`` Protocol keeps the two interchangeable.

Tenant scoping is the caller's responsibility: compose ``buyer_id`` as
``"{tenant.slug}:{from_number}"`` so memories from different tenants never collide.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
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
