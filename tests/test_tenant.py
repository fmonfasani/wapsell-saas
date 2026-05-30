"""Tests for the multi-tenant subsystem: repository, router, supervisor + webhook routing."""

from __future__ import annotations

import hashlib
import hmac
import json

from fastapi.testclient import TestClient
import httpx
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from waseller import Tenant, TenantStatus, WasellerClient
from waseller.tenant import (
    InMemoryTenantRepository,
    InMemoryTenantSpawner,
    TenantRouter,
    TenantSupervisor,
    UnknownTenantError,
)
from waseller.whatsapp.webhook import extract_phone_number_id

pytestmark = pytest.mark.unit


def _tenant(slug: str = "acme", pnid: str | None = "549111") -> Tenant:
    return Tenant(name=f"{slug.title()} Store", slug=slug, whatsapp_phone_number_id=pnid)


# --- repository -------------------------------------------------------------


class TestRepository:
    def test_add_and_get_roundtrip(self) -> None:
        repo = InMemoryTenantRepository()
        t = repo.add(_tenant())
        assert repo.get(t.id) == t

    def test_get_unknown_returns_none(self) -> None:
        assert InMemoryTenantRepository().get("nope") is None

    def test_lookups_by_slug_and_phone(self) -> None:
        repo = InMemoryTenantRepository()
        repo.add(_tenant(slug="alpha", pnid="111"))
        repo.add(_tenant(slug="beta", pnid="222"))
        alpha = repo.by_slug("alpha")
        beta = repo.by_phone_number_id("222")
        assert alpha is not None and alpha.slug == "alpha"
        assert beta is not None and beta.slug == "beta"
        assert repo.by_slug("missing") is None
        assert repo.by_phone_number_id("000") is None

    def test_update_requires_existing(self) -> None:
        repo = InMemoryTenantRepository()
        with pytest.raises(KeyError):
            repo.update(_tenant())

    def test_list_returns_all(self) -> None:
        repo = InMemoryTenantRepository()
        repo.add(_tenant(slug="a"))
        repo.add(_tenant(slug="b"))
        assert {t.slug for t in repo.list_all()} == {"a", "b"}


# --- router -----------------------------------------------------------------


class TestRouter:
    def test_resolve_finds_tenant_by_phone(self) -> None:
        repo = InMemoryTenantRepository()
        repo.add(_tenant(slug="acme", pnid="999"))
        assert TenantRouter(repo).resolve("999").slug == "acme"

    def test_resolve_unknown_raises(self) -> None:
        with pytest.raises(UnknownTenantError, match="no tenant"):
            TenantRouter(InMemoryTenantRepository()).resolve("missing")

    def test_try_resolve_returns_none_on_miss(self) -> None:
        assert TenantRouter(InMemoryTenantRepository()).try_resolve("x") is None


# --- supervisor -------------------------------------------------------------


class TestSupervisor:
    async def test_bring_up_marks_active_and_spawns(self) -> None:
        repo = InMemoryTenantRepository()
        spawner = InMemoryTenantSpawner()
        t = repo.add(_tenant())
        sup = TenantSupervisor(repo, spawner)

        updated = await sup.bring_up(t.id)
        assert updated.status is TenantStatus.ACTIVE
        assert await spawner.is_running(t.id)

    async def test_bring_down_marks_suspended_and_stops(self) -> None:
        repo = InMemoryTenantRepository()
        spawner = InMemoryTenantSpawner()
        t = repo.add(_tenant())
        sup = TenantSupervisor(repo, spawner)
        await sup.bring_up(t.id)

        updated = await sup.bring_down(t.id)
        assert updated.status is TenantStatus.SUSPENDED
        assert not await spawner.is_running(t.id)

    async def test_health_reports_status_and_running(self) -> None:
        repo = InMemoryTenantRepository()
        spawner = InMemoryTenantSpawner()
        t = repo.add(_tenant())
        sup = TenantSupervisor(repo, spawner)

        h = await sup.health(t.id)
        assert h.status is TenantStatus.PROVISIONING
        assert h.running is False

        await sup.bring_up(t.id)
        h2 = await sup.health(t.id)
        assert h2.status is TenantStatus.ACTIVE
        assert h2.running is True

    async def test_unknown_tenant_raises(self) -> None:
        sup = TenantSupervisor(InMemoryTenantRepository(), InMemoryTenantSpawner())
        with pytest.raises(KeyError):
            await sup.bring_up("nope")


# --- client wiring ----------------------------------------------------------


class TestClientWiring:
    def test_creating_a_tenant_makes_it_routable(self) -> None:
        client = WasellerClient()
        t = client.create_tenant("Acme", "acme")
        # phone_number_id is set later (onboarding); simulate by updating via repo.
        client.tenants.repository.update(
            t.model_copy(update={"whatsapp_phone_number_id": "549999"})
        )
        assert client.router.resolve("549999").slug == "acme"


# --- webhook helpers --------------------------------------------------------


def _meta_payload(phone_number_id: str, message_text: str = "hola") -> dict[str, object]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "type": "text",
                                    "from": "549111",
                                    "id": "m-1",
                                    "text": {"body": message_text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def test_extract_phone_number_id_returns_first_match() -> None:
    assert extract_phone_number_id(_meta_payload("abc-123")) == "abc-123"


def test_extract_phone_number_id_returns_none_on_missing() -> None:
    assert extract_phone_number_id({"entry": []}) is None


# --- webhook routing end-to-end --------------------------------------------


class TestWebhookRouting:
    """Round-trip: signed POST → router resolves → tenant slug echoed back."""

    def _signed_post(
        self, client: TestClient, secret: str, body: dict[str, object]
    ) -> httpx.Response:
        raw = json.dumps(body).encode()
        sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
        return client.post("/webhook", content=raw, headers={"X-Hub-Signature-256": sig})

    def test_unknown_phone_returns_200_with_note(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("META_APP_SECRET", "shh")
        with TestClient(app) as client:
            res = self._signed_post(client, "shh", _meta_payload("does-not-exist"))
        assert res.status_code == 200
        assert "no tenant" in res.text

    def test_known_phone_routes_to_tenant_and_acks_count(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("META_APP_SECRET", "shh")
        # Register a tenant on the same client instance the app uses.
        t = live_client.create_tenant("Routed", "routed-slug")
        live_client.tenants.repository.update(
            t.model_copy(update={"whatsapp_phone_number_id": "ROUTE-PN"})
        )

        with TestClient(app) as client:
            res = self._signed_post(client, "shh", _meta_payload("ROUTE-PN"))
        assert res.status_code == 200
        assert "received 1 for routed-slug" in res.text

    def test_bad_signature_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("META_APP_SECRET", "shh")
        with TestClient(app) as client:
            res = client.post(
                "/webhook",
                content=b"{}",
                headers={"X-Hub-Signature-256": "sha256=deadbeef"},
            )
        assert res.status_code == 401
