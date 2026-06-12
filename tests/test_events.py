"""Tests for the in-memory event bus."""

from __future__ import annotations

import pytest

from wapsell.events import Event, EventBusPort, InMemoryEventBus

pytestmark = pytest.mark.unit


class TestInMemoryEventBus:
    async def test_publish_records_the_event(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(Event(type="tenant.onboarded", payload={"id": "t1"}))
        assert len(bus.events) == 1
        assert bus.events[0].type == "tenant.onboarded"
        assert bus.events[0].payload == {"id": "t1"}

    async def test_subscribers_receive_events_in_order(self) -> None:
        bus = InMemoryEventBus()
        seen: list[str] = []

        async def handler(event: Event) -> None:
            seen.append(event.type)

        await bus.subscribe(handler)
        await bus.publish(Event(type="a"))
        await bus.publish(Event(type="b"))
        assert seen == ["a", "b"]

    async def test_multiple_subscribers_each_get_each_event(self) -> None:
        bus = InMemoryEventBus()
        a: list[Event] = []
        b: list[Event] = []

        async def h_a(event: Event) -> None:
            a.append(event)

        async def h_b(event: Event) -> None:
            b.append(event)

        await bus.subscribe(h_a)
        await bus.subscribe(h_b)
        await bus.publish(Event(type="x"))
        assert len(a) == 1
        assert len(b) == 1

    async def test_subscribe_during_publish_does_not_receive_in_flight_event(
        self,
    ) -> None:
        # Guards against re-entrancy: if a handler subscribes a new handler
        # mid-publish, the new one must not see the event currently being
        # delivered (otherwise reasoning about ordering becomes impossible).
        bus = InMemoryEventBus()
        late_seen: list[Event] = []

        async def late_handler(event: Event) -> None:
            late_seen.append(event)

        async def early(event: Event) -> None:
            await bus.subscribe(late_handler)

        await bus.subscribe(early)
        await bus.publish(Event(type="boom"))
        assert late_seen == []

    async def test_by_type_filters_recorded_events(self) -> None:
        bus = InMemoryEventBus()
        await bus.publish(Event(type="a"))
        await bus.publish(Event(type="b"))
        await bus.publish(Event(type="a"))
        assert len(bus.by_type("a")) == 2
        assert len(bus.by_type("b")) == 1

    def test_satisfies_protocol(self) -> None:
        bus = InMemoryEventBus()
        assert isinstance(bus, EventBusPort)
