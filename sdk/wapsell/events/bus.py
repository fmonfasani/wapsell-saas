"""Minimal in-process event bus.

Onboarding emits ``tenant.onboarded``; future phases will emit ``provider.*``,
``conversation.*``, etc. The port is async because real adapters (Redis Streams,
Kafka, NATS) are I/O-bound; the in-memory implementation just appends + invokes
handlers synchronously within an ``await``.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Protocol, runtime_checkable

EventHandler = Callable[["Event"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Event:
    """An immutable domain event. ``type`` is dotted: ``tenant.onboarded``."""

    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: datetime = field(default_factory=lambda: datetime.now(UTC))


@runtime_checkable
class EventBusPort(Protocol):
    """Publish/subscribe boundary. In-memory by default; Redis/Kafka later."""

    async def publish(self, event: Event) -> None: ...
    async def subscribe(self, handler: EventHandler) -> None: ...


@dataclass(slots=True)
class InMemoryEventBus:
    """Records every event + fans out to subscribers. Test-friendly."""

    events: list[Event] = field(default_factory=list)
    _handlers: list[EventHandler] = field(default_factory=list)

    async def publish(self, event: Event) -> None:
        self.events.append(event)
        # Iterate over a snapshot so a handler that subscribes during publish
        # doesn't receive the in-flight event (avoids re-entrancy surprises).
        for handler in list(self._handlers):
            await handler(event)

    async def subscribe(self, handler: EventHandler) -> None:
        self._handlers.append(handler)

    def by_type(self, event_type: str) -> list[Event]:
        return [e for e in self.events if e.type == event_type]
