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
    def test_get_returns_rendered_soul_and_default_config(self, http: TestClient) -> None:
        created = http.post(
            "/tenants", json={"name": "Soulful Shop", "slug": "soulful-shop"}
        ).json()
        res = http.get(f"/tenants/{created['id']}/soul")
        assert res.status_code == 200
        body = res.json()
        assert "Soulful Shop" in body["soul"]
        # No PUT yet -> config falls through to the SDK defaults.
        assert body["config"]["language"] == "español"
        assert body["config"]["tone"] == "cercano y profesional"
        assert body["config"]["include_skills"] is True

    def test_404_when_missing(self, http: TestClient) -> None:
        res = http.get("/tenants/x/soul")
        assert res.status_code == 404

    def test_put_persists_config_and_returns_new_render(self, http: TestClient) -> None:
        created = http.post(
            "/tenants", json={"name": "Editable Shop", "slug": "editable-shop"}
        ).json()

        custom = {
            "language": "English",
            "tone": "formal",
            "mission": "Sell premium watches to wealthy customers.",
            "rules": [
                "Never quote a price without checking stock.",
                "Always confirm shipping address.",
            ],
            "include_skills": False,
        }
        res = http.put(f"/tenants/{created['id']}/soul", json=custom)
        assert res.status_code == 200
        body = res.json()
        # The rendered prompt now reflects the new config.
        assert "English" in body["soul"]
        assert "formal" in body["soul"]
        assert "Sell premium watches" in body["soul"]
        # include_skills=False -> no skills section in the rendered prompt.
        assert "catalog-lookup" not in body["soul"]
        # Config echoed back so the dashboard can pre-fill the form on next load.
        assert body["config"] == custom

    def test_put_config_is_persisted_across_subsequent_gets(self, http: TestClient) -> None:
        created = http.post(
            "/tenants", json={"name": "Persistent Shop", "slug": "persistent-shop"}
        ).json()
        custom = {
            "language": "português",
            "tone": "informal",
            "mission": "Vender açaí 24/7.",
            "rules": ["Não inventar preços."],
            "include_skills": True,
        }
        http.put(f"/tenants/{created['id']}/soul", json=custom)
        res = http.get(f"/tenants/{created['id']}/soul")
        assert res.status_code == 200
        body = res.json()
        assert body["config"] == custom
        assert "português" in body["soul"]

    def test_put_404_when_tenant_missing(self, http: TestClient) -> None:
        res = http.put(
            "/tenants/does-not-exist/soul",
            json={
                "language": "x",
                "tone": "y",
                "mission": "z",
                "rules": ["r"],
                "include_skills": True,
            },
        )
        assert res.status_code == 404


class TestTenantHandoff:
    """Endpoints behind the dashboard /tenants/[id]/handoff page. PR #25 added
    bot → human escalation; the API surface mirrors /soul exactly so the form
    layer can copy the same GET-prefill / PUT-overwrite pattern."""

    def test_get_returns_defaults_when_unconfigured(self, http: TestClient) -> None:
        created = http.post(
            "/tenants", json={"name": "Handoff Shop", "slug": "handoff-default"}
        ).json()
        res = http.get(f"/tenants/{created['id']}/handoff")
        assert res.status_code == 200
        body = res.json()
        # New tenants land on safe defaults — disabled by default so the agent
        # behavior doesn't change without explicit opt-in.
        assert body["config"]["enabled"] is False
        assert "humano" in body["config"]["keywords"]
        assert body["config"]["webhook_url"] is None

    def test_get_404_when_tenant_missing(self, http: TestClient) -> None:
        assert http.get("/tenants/does-not-exist/handoff").status_code == 404

    def test_put_persists_config(self, http: TestClient) -> None:
        created = http.post("/tenants", json={"name": "Handoff PUT", "slug": "handoff-put"}).json()
        body = {
            "enabled": True,
            "keywords": ["humano", "vendedor"],
            "webhook_url": "https://hooks.example/x",
            "handoff_message": "Te paso con un humano ya mismo.",
            "auto_pause_hours": 12,
        }
        res = http.put(f"/tenants/{created['id']}/handoff", json=body)
        assert res.status_code == 200
        assert res.json()["config"] == body

        # GET reflects the persisted state on the next request — proves the
        # repository write took.
        again = http.get(f"/tenants/{created['id']}/handoff").json()
        assert again["config"] == body

    def test_put_404_when_tenant_missing(self, http: TestClient) -> None:
        res = http.put(
            "/tenants/does-not-exist/handoff",
            json={
                "enabled": True,
                "keywords": ["humano"],
                "webhook_url": None,
                "handoff_message": "Te paso con un humano.",
            },
        )
        assert res.status_code == 404


class TestMessageTemplates:
    """CRUD endpoints for the dashboard Templates UI. The tests cover the
    lifecycle a real customer walks through: create draft → submit → approve
    (with auto-stamping of submitted_at/approved_at) → delete. Plus the
    uniqueness-conflict and cross-tenant-isolation guards."""

    def _new_tenant(self, http: TestClient, slug: str) -> str:
        res = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return str(res["id"])

    def test_create_returns_201_with_draft_status(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-create")
        res = http.post(
            f"/tenants/{tid}/templates",
            json={
                "name": "welcome",
                "body": "¡Hola {{1}}! Bienvenido a {{2}}.",
                "language": "es_AR",
                "category": "UTILITY",
            },
        )
        assert res.status_code == 201
        body = res.json()
        assert body["status"] == "DRAFT"
        assert body["submitted_at"] is None
        assert body["approved_at"] is None
        assert body["vendor_template_id"] is None

    def test_create_duplicate_name_language_returns_409(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-dup")
        http.post(
            f"/tenants/{tid}/templates",
            json={"name": "welcome", "body": "x"},
        )
        res = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "welcome", "body": "y"},
        )
        assert res.status_code == 409
        assert "already exists" in res.json()["detail"]

    def test_same_name_different_language_is_allowed(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-multi-lang")
        a = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "welcome", "body": "Hola", "language": "es_AR"},
        )
        b = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "welcome", "body": "Hi", "language": "en_US"},
        )
        assert a.status_code == 201
        assert b.status_code == 201

    def test_list_returns_tenant_templates_only(self, http: TestClient) -> None:
        tid_a = self._new_tenant(http, "tpl-scope-a")
        tid_b = self._new_tenant(http, "tpl-scope-b")
        http.post(f"/tenants/{tid_a}/templates", json={"name": "a-only", "body": "x"})
        http.post(f"/tenants/{tid_b}/templates", json={"name": "b-only", "body": "y"})

        list_a = http.get(f"/tenants/{tid_a}/templates").json()
        assert [t["name"] for t in list_a] == ["a-only"]

    def test_patch_status_submitted_auto_stamps_submitted_at(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-submit")
        created = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "x", "body": "hola"},
        ).json()
        res = http.patch(
            f"/tenants/{tid}/templates/{created['id']}",
            json={"status": "SUBMITTED", "vendor_template_id": "meta-abc-123"},
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "SUBMITTED"
        assert body["submitted_at"] is not None
        assert body["approved_at"] is None
        assert body["vendor_template_id"] == "meta-abc-123"

    def test_patch_status_approved_auto_stamps_approved_at(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-approve")
        created = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "y", "body": "hola"},
        ).json()
        res = http.patch(
            f"/tenants/{tid}/templates/{created['id']}",
            json={"status": "APPROVED"},
        )
        assert res.status_code == 200
        assert res.json()["approved_at"] is not None

    def test_patch_status_rejected_carries_reason(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-reject")
        created = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "z", "body": "hola"},
        ).json()
        res = http.patch(
            f"/tenants/{tid}/templates/{created['id']}",
            json={
                "status": "REJECTED",
                "rejection_reason": "Template body contains a forbidden URL.",
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["status"] == "REJECTED"
        assert "forbidden URL" in body["rejection_reason"]

    def test_patch_template_from_other_tenant_returns_404(self, http: TestClient) -> None:
        tid_a = self._new_tenant(http, "tpl-iso-a")
        tid_b = self._new_tenant(http, "tpl-iso-b")
        created_in_a = http.post(
            f"/tenants/{tid_a}/templates",
            json={"name": "n", "body": "x"},
        ).json()
        # Patch trying to act through tenant B → 404, no leak.
        res = http.patch(
            f"/tenants/{tid_b}/templates/{created_in_a['id']}",
            json={"name": "stolen"},
        )
        assert res.status_code == 404

    def test_delete_removes_template(self, http: TestClient) -> None:
        tid = self._new_tenant(http, "tpl-del")
        created = http.post(
            f"/tenants/{tid}/templates",
            json={"name": "n", "body": "x"},
        ).json()
        d = http.delete(f"/tenants/{tid}/templates/{created['id']}")
        assert d.status_code == 204
        # And the list no longer shows it.
        listed = http.get(f"/tenants/{tid}/templates").json()
        assert all(t["id"] != created["id"] for t in listed)


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
