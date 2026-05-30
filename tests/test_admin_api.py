"""Tests for the /tenants admin endpoints (consumed by the Next.js dashboard)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


class TestListTenants:
    def test_returns_a_list(self, http: TestClient) -> None:
        res = http.get("/tenants")
        assert res.status_code == 200
        assert isinstance(res.json(), list)

    def test_includes_a_freshly_created_tenant(self, http: TestClient) -> None:
        before = {t["slug"] for t in http.get("/tenants").json()}
        live_client.create_tenant("List Sample", "list-sample-x")
        after = {t["slug"] for t in http.get("/tenants").json()}
        assert "list-sample-x" in after - before


class TestCreateTenant:
    def test_201_with_minimal_body(self, http: TestClient) -> None:
        res = http.post("/tenants", json={"name": "Acme Admin", "slug": "acme-admin-1"})
        assert res.status_code == 201
        body = res.json()
        assert body["slug"] == "acme-admin-1"
        assert body["status"] == "PROVISIONING"
        assert body["whatsapp_phone_number_id"] is None
        assert body["id"]
        assert body["created_at"]

    def test_201_with_phone_number_id_pre_assigned(self, http: TestClient) -> None:
        res = http.post(
            "/tenants",
            json={"name": "Pre-Wired", "slug": "pre-wired", "whatsapp_phone_number_id": "PNID-1"},
        )
        assert res.status_code == 201
        assert res.json()["whatsapp_phone_number_id"] == "PNID-1"

    def test_409_on_duplicate_slug(self, http: TestClient) -> None:
        http.post("/tenants", json={"name": "Dup", "slug": "dup-slug"})
        res = http.post("/tenants", json={"name": "Dup 2", "slug": "dup-slug"})
        assert res.status_code == 409
        assert "already exists" in res.json()["detail"]

    def test_422_when_required_field_missing(self, http: TestClient) -> None:
        res = http.post("/tenants", json={"name": "No Slug"})
        assert res.status_code == 422


class TestGetTenant:
    def test_200_with_existing(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Getter", "slug": "getter"}).json()
        res = http.get(f"/tenants/{created['id']}")
        assert res.status_code == 200
        assert res.json()["slug"] == "getter"

    def test_404_when_missing(self, http: TestClient) -> None:
        res = http.get("/tenants/does-not-exist")
        assert res.status_code == 404
        assert res.json()["detail"] == "tenant not found"


class TestUpdateTenant:
    def test_set_phone_number_id_makes_tenant_routable(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Patchable", "slug": "patchable"}).json()
        res = http.patch(f"/tenants/{created['id']}", json={"whatsapp_phone_number_id": "WIRED-PN"})
        assert res.status_code == 200
        assert res.json()["whatsapp_phone_number_id"] == "WIRED-PN"
        # Router can now resolve it.
        assert live_client.router.resolve("WIRED-PN").slug == "patchable"

    def test_change_model(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Modeler", "slug": "modeler"}).json()
        res = http.patch(f"/tenants/{created['id']}", json={"model": "anthropic/claude-3-haiku"})
        assert res.status_code == 200
        assert res.json()["model"] == "anthropic/claude-3-haiku"

    def test_404_when_missing(self, http: TestClient) -> None:
        res = http.patch("/tenants/nope", json={"model": "x"})
        assert res.status_code == 404

    def test_empty_body_is_noop(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Noop", "slug": "noop-tenant"}).json()
        res = http.patch(f"/tenants/{created['id']}", json={})
        assert res.status_code == 200
        assert res.json()["slug"] == "noop-tenant"


class TestTenantSoul:
    def test_returns_rendered_soul(self, http: TestClient) -> None:
        created = http.post(
            "/tenants", json={"name": "Soulful Shop", "slug": "soulful-shop"}
        ).json()
        res = http.get(f"/tenants/{created['id']}/soul")
        assert res.status_code == 200
        body = res.json()
        assert "soul" in body
        assert "Soulful Shop" in body["soul"]

    def test_404_when_missing(self, http: TestClient) -> None:
        res = http.get("/tenants/x/soul")
        assert res.status_code == 404


class TestCors:
    def test_preflight_for_localhost_dashboard(self, http: TestClient) -> None:
        res = http.options(
            "/tenants",
            headers={
                "Origin": "http://localhost:3000",
                "Access-Control-Request-Method": "POST",
            },
        )
        assert res.status_code in (200, 204)
        assert res.headers.get("access-control-allow-origin") == "http://localhost:3000"
