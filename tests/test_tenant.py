"""Tests for the multi-tenant subsystem: repository, router, supervisor + webhook routing."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from waseller import Tenant, TenantStatus, WasellerClient
from waseller.tenant import (
    InMemoryTenantRepository,
    InMemoryTenantSpawner,
    PostgresTenantRepository,
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

    def _signed_post(self, client: TestClient, secret: str, body: dict[str, object]) -> Any:
        # Return type is Any (not httpx.Response) because starlette typed
        # TestClient.post as Any in older releases; newer ones return httpx.Response
        # and would flag an explicit annotation as redundant. Callers only need
        # status_code/text/json(), all of which work either way.
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


# --- Postgres adapter (unit-level, mocked DB-API connection) ----------------


class _FakeCursor:
    """Minimal PEP 249 cursor. Records executed statements and replays a queue
    of canned result sets so each .execute() can return different rows."""

    def __init__(self, results: Sequence[Sequence[tuple[object, ...]]]) -> None:
        self._results = list(results)
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self._last: list[tuple[object, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None: ...

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, params))
        self._last = list(self._results.pop(0)) if self._results else []

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._last)


class _FakeConn:
    """Connection that hands out one cursor at a time + counts commits."""

    def __init__(self, results: Sequence[Sequence[tuple[object, ...]]] = ()) -> None:
        self.cursors: list[_FakeCursor] = []
        self._results = list(results)
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        cur = _FakeCursor(self._results)
        self.cursors.append(cur)
        return cur

    def commit(self) -> None:
        self.commits += 1


def _row(t: Tenant) -> tuple[object, ...]:
    return (
        t.id,
        t.name,
        t.slug,
        t.status.value,
        t.whatsapp_phone_number_id,
        t.model,
        t.created_at,
    )


class TestPostgresTenantRepository:
    def test_add_executes_insert_and_commits(self) -> None:
        conn = _FakeConn()
        repo = PostgresTenantRepository(conn)
        t = _tenant(slug="acme", pnid="549999")

        returned = repo.add(t)

        assert returned is t
        assert conn.commits == 1
        sql, params = conn.cursors[0].executed[0]
        assert sql.startswith("INSERT INTO tenants")
        # params order: id, name, slug, status, phone_number_id, model, created_at
        assert params[0] == t.id
        assert params[2] == "acme"
        assert params[3] == t.status.value
        assert params[4] == "549999"

    def test_get_decodes_row_to_tenant(self) -> None:
        t = _tenant(slug="alpha", pnid="111")
        conn = _FakeConn(results=[[_row(t)]])
        repo = PostgresTenantRepository(conn)

        got = repo.get(t.id)

        assert got is not None
        assert got.id == t.id
        assert got.slug == "alpha"
        assert got.status is TenantStatus.PROVISIONING
        sql, params = conn.cursors[0].executed[0]
        assert "WHERE id = %s" in sql
        assert params == (t.id,)

    def test_get_returns_none_when_no_rows(self) -> None:
        conn = _FakeConn(results=[[]])
        assert PostgresTenantRepository(conn).get("missing") is None

    def test_by_slug_and_by_phone_use_distinct_queries(self) -> None:
        t = _tenant(slug="beta", pnid="222")
        conn = _FakeConn(results=[[_row(t)], [_row(t)]])
        repo = PostgresTenantRepository(conn)

        assert repo.by_slug("beta") is not None
        assert repo.by_phone_number_id("222") is not None
        assert "WHERE slug = %s" in conn.cursors[0].executed[0][0]
        assert "WHERE whatsapp_phone_number_id = %s" in conn.cursors[1].executed[0][0]

    def test_list_all_orders_by_created_at(self) -> None:
        t1 = _tenant(slug="a", pnid="1")
        t2 = _tenant(slug="b", pnid="2")
        conn = _FakeConn(results=[[_row(t1), _row(t2)]])

        results = PostgresTenantRepository(conn).list_all()

        assert {r.slug for r in results} == {"a", "b"}
        sql, _ = conn.cursors[0].executed[0]
        assert "ORDER BY created_at" in sql

    def test_update_unknown_raises_and_does_not_commit(self) -> None:
        # First cursor.execute is the existence check; it returns no rows.
        conn = _FakeConn(results=[[]])
        repo = PostgresTenantRepository(conn)
        with pytest.raises(KeyError, match="unknown tenant"):
            repo.update(_tenant())
        assert conn.commits == 0

    def test_update_existing_runs_update_and_commits(self) -> None:
        t = _tenant(slug="updated", pnid="555")
        # First execute (existence check) returns a non-empty row; second is the UPDATE.
        conn = _FakeConn(results=[[(1,)], []])
        repo = PostgresTenantRepository(conn)

        returned = repo.update(t)

        assert returned is t
        assert conn.commits == 1
        # Cursor shared across both execs via the single `with self._conn.cursor()` block.
        execs = conn.cursors[0].executed
        assert execs[0][0].startswith("SELECT 1 FROM tenants WHERE id")
        assert execs[1][0].startswith("UPDATE tenants")
        # UPDATE params order: name, slug, status, phone_number_id, model, id
        assert execs[1][1] == (t.name, "updated", t.status.value, "555", t.model, t.id)

    def test_row_to_tenant_parses_iso_timestamp(self) -> None:
        # psycopg2 may hand back created_at as an ISO string; the adapter must parse it.
        when = datetime(2026, 1, 1, 12, 0, 0, tzinfo=UTC)
        row = (
            "id-1",
            "Acme",
            "acme",
            "ACTIVE",
            "549111",
            "openai/gpt-4o-mini",
            when.isoformat(),
        )
        conn = _FakeConn(results=[[row]])
        got = PostgresTenantRepository(conn).get("id-1")
        assert got is not None
        assert got.status is TenantStatus.ACTIVE
        assert got.created_at == when
