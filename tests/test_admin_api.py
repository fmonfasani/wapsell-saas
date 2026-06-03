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


class TestDeepHealth:
    """Exercises the /health/deep endpoint with all probes in the 'skipped'
    state — the unit env has no Postgres/OpenRouter/Meta credentials, so the
    payload should still be 200 with all checks reported as skipped, not
    error. Live integrations (real Postgres / OpenRouter / Meta) are out of
    scope for the unit suite."""

    def test_returns_200_with_all_skipped_when_no_env_set(
        self, http: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Strip any inherited env so all three probes go down the 'skipped' path.
        for var in ("OPENROUTER_API_KEY", "META_ACCESS_TOKEN", "META_PHONE_NUMBER_ID"):
            monkeypatch.delenv(var, raising=False)
        res = http.get("/health/deep")
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "ok"
        assert body["service"] == "waseller-api"
        assert set(body["checks"].keys()) == {"postgres", "openrouter", "meta"}
        # In unit env: no WASELLER_POSTGRES_URL, no OPENROUTER, no META.
        # All three should be skipped (not error), so the rollup is 'ok'.
        assert all(c["status"] == "skipped" for c in body["checks"].values())


class TestCatalogIngest:
    def test_201_ingests_facts_and_returns_count(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Catalog A", "slug": "catalog-a"}).json()
        payload = {
            "source": "demo-v1",
            "facts": [
                {"content": "Camiseta XL azul $9000", "metadata": {"sku": "CAM-XL-AZ"}},
                {"content": "Pantalon talle M negro $14000", "metadata": {"sku": "PAN-M-NG"}},
            ],
        }
        res = http.post(f"/tenants/{created['id']}/catalog/facts", json=payload)
        assert res.status_code == 201
        body = res.json()
        assert body["tenant_id"] == created["id"]
        assert body["ingested"] == 2
        assert len(body["fact_ids"]) == 2

    def test_ingested_facts_appear_in_listing(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Catalog B", "slug": "catalog-b"}).json()
        http.post(
            f"/tenants/{created['id']}/catalog/facts",
            json={"facts": [{"content": "Mochila urbana 25L"}]},
        )
        listed = http.get(f"/tenants/{created['id']}/catalog/facts").json()
        assert any("Mochila" in f["content"] for f in listed)
        # Default source label propagates.
        assert all(f["source"] == "manual-ingest" for f in listed if "Mochila" in f["content"])

    def test_facts_are_tenant_scoped(self, http: TestClient) -> None:
        a = http.post("/tenants", json={"name": "Scope A", "slug": "scope-a"}).json()
        b = http.post("/tenants", json={"name": "Scope B", "slug": "scope-b"}).json()
        http.post(
            f"/tenants/{a['id']}/catalog/facts",
            json={"facts": [{"content": "AAA-unique"}]},
        )
        contents_b = [f["content"] for f in http.get(f"/tenants/{b['id']}/catalog/facts").json()]
        assert "AAA-unique" not in contents_b

    def test_ingest_into_unknown_tenant_404(self, http: TestClient) -> None:
        res = http.post(
            "/tenants/nope/catalog/facts",
            json={"facts": [{"content": "x"}]},
        )
        assert res.status_code == 404

    def test_empty_facts_list_rejected(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Empty", "slug": "empty-cat"}).json()
        res = http.post(f"/tenants/{created['id']}/catalog/facts", json={"facts": []})
        assert res.status_code == 422

    def test_list_unknown_tenant_404(self, http: TestClient) -> None:
        res = http.get("/tenants/nope/catalog/facts")
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
