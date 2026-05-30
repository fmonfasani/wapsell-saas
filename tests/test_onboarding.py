"""Tests for the Meta Embedded Signup → tenant onboarding flow."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from waseller.client import WasellerClient
from waseller.events import InMemoryEventBus
from waseller.models import TenantStatus
from waseller.onboarding import (
    MetaSignupPayload,
    OnboardingFlow,
    slugify,
)

pytestmark = pytest.mark.unit


class TestSlugify:
    @pytest.mark.parametrize(
        ("name", "expected"),
        [
            ("Acme Corp", "acme-corp"),
            ("Acme & Co!", "acme-co"),
            ("  Padded  ", "padded"),
            ("---weird---", "weird"),
            ("", "tenant"),
            ("ÜberShop", "bershop"),  # non-ASCII stripped (no transliteration here)
            ("Ñoño", "oo"),
        ],
    )
    def test_normalizes(self, name: str, expected: str) -> None:
        assert slugify(name) == expected


class TestOnboardingFlow:
    @pytest.fixture
    def client(self) -> WasellerClient:
        # Fresh isolated stack — onboarding mutates the repo/spawner/event-bus.
        return WasellerClient(event_bus=InMemoryEventBus())

    async def test_creates_tenant_renders_soul_spawns_and_emits_event(
        self, client: WasellerClient
    ) -> None:
        bus = client.event_bus
        assert isinstance(bus, InMemoryEventBus)

        result = await client.onboarding.run(
            MetaSignupPayload(
                phone_number_id="PN-123",
                business_name="Acme Corp",
                waba_id="WABA-1",
                business_id="BIZ-1",
            )
        )

        assert result.is_new is True
        assert result.tenant.slug == "acme-corp"
        assert result.tenant.whatsapp_phone_number_id == "PN-123"
        assert result.tenant.status == TenantStatus.ACTIVE  # supervisor.bring_up

        # Routing works end-to-end after onboarding.
        assert client.router.resolve("PN-123").id == result.tenant.id

        # tenant.onboarded was emitted with the canonical payload.
        events = bus.by_type("tenant.onboarded")
        assert len(events) == 1
        assert events[0].payload["tenant_id"] == result.tenant.id
        assert events[0].payload["phone_number_id"] == "PN-123"
        assert events[0].payload["waba_id"] == "WABA-1"

    async def test_idempotent_on_phone_number_id(self, client: WasellerClient) -> None:
        # Meta retries the callback when we don't return 2xx — replays must NOT
        # create duplicates. We key off phone_number_id (the stable identifier).
        payload = MetaSignupPayload(phone_number_id="PN-DUP", business_name="Dup Inc")
        first = await client.onboarding.run(payload)
        second = await client.onboarding.run(payload)

        assert first.is_new is True
        assert second.is_new is False
        assert second.tenant.id == first.tenant.id
        # Only one tenant.onboarded event — replay is silent.
        assert isinstance(client.event_bus, InMemoryEventBus)
        assert len(client.event_bus.by_type("tenant.onboarded")) == 1

    async def test_collision_appends_numeric_suffix(self, client: WasellerClient) -> None:
        a = await client.onboarding.run(
            MetaSignupPayload(phone_number_id="PN-A", business_name="Same Name")
        )
        b = await client.onboarding.run(
            MetaSignupPayload(phone_number_id="PN-B", business_name="Same Name")
        )
        c = await client.onboarding.run(
            MetaSignupPayload(phone_number_id="PN-C", business_name="Same Name")
        )
        assert a.tenant.slug == "same-name"
        assert b.tenant.slug == "same-name-2"
        assert c.tenant.slug == "same-name-3"

    async def test_uses_default_event_bus_when_unspecified(self) -> None:
        # The flow should still work without injecting a bus — it falls back to
        # an in-memory one so callers don't have to wire one for tests.
        client = WasellerClient()
        flow = OnboardingFlow(client.tenants, client.supervisor)
        result = await flow.run(MetaSignupPayload(phone_number_id="PN-NB", business_name="No Bus"))
        assert result.is_new is True


class TestConnectWhatsAppEndpoint:
    @pytest.fixture
    def http(self) -> TestClient:
        return TestClient(app)

    def test_201_on_first_call_then_replay_returns_is_new_false(self, http: TestClient) -> None:
        body = {"phone_number_id": "PN-EP-1", "business_name": "Endpoint Shop"}
        first = http.post("/tenants/connect-whatsapp", json=body)
        assert first.status_code == 201
        assert first.json()["is_new"] is True

        second = http.post("/tenants/connect-whatsapp", json=body)
        assert second.status_code == 201
        assert second.json()["is_new"] is False
        assert second.json()["tenant_id"] == first.json()["tenant_id"]

    def test_makes_tenant_routable_on_the_live_client(self, http: TestClient) -> None:
        res = http.post(
            "/tenants/connect-whatsapp",
            json={"phone_number_id": "PN-EP-LIVE", "business_name": "Live Routable"},
        )
        assert res.status_code == 201
        assert live_client.router.resolve("PN-EP-LIVE").slug.startswith("live-routable")

    def test_422_when_required_field_missing(self, http: TestClient) -> None:
        res = http.post("/tenants/connect-whatsapp", json={"business_name": "No Phone"})
        assert res.status_code == 422
