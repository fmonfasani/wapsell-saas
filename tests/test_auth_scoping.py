"""Tests for the auth-enforcement layer (PR #27).

When ``WAPSELL_AUTH_REQUIRED=true``:

- ``GET /tenants`` returns only the caller's tenant (TENANT role) or all
  tenants (ADMIN). Unauthenticated callers get 401.
- Tenant-scoped endpoints (/soul, /handoff, /catalog/facts, /conversations
  etc.) return 401 for unauthenticated callers, 403 for cross-tenant
  peeking, and the actual payload for the owner or any ADMIN.
- ``POST /tenants`` and ``POST /auth/register`` are ADMIN-only.

When the flag is off (default), every test from the existing suites keeps
passing — that's verified by the rest of the suite running unchanged.
"""

from __future__ import annotations

from collections.abc import Generator

from fastapi.testclient import TestClient
import pytest
from services.api.main import _auth_service, app
from services.api.main import _client as live_client

from wapsell.models import UserRole

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


@pytest.fixture
def auth_on(monkeypatch: pytest.MonkeyPatch) -> Generator[None, None, None]:
    """Flip ``WAPSELL_AUTH_REQUIRED=true`` for the duration of a test. Pair
    with a fresh tenant_id + email so other tests don't see leaked state."""
    monkeypatch.setenv("WAPSELL_AUTH_REQUIRED", "true")
    yield


def _new_tenant_and_user(
    _http: TestClient,
    *,
    slug: str,
    email: str,
    role: UserRole,
) -> tuple[str, str]:
    """Create a tenant + a user scoped to it, returning (tenant_id, session_token).

    We provision the tenant through the SDK directly because the POST
    endpoint is admin-only under enforcement, and we can't have an admin
    until we have a tenant. The auth_service is hit directly for the same
    reason — /auth/register is admin-only too."""
    tenant = live_client.create_tenant(slug.title(), slug)
    _auth_service.register(
        email=email,
        password="hunter2hunter2",
        role=role,
        tenant_id=tenant.id if role == UserRole.TENANT else None,
    )
    _, session = _auth_service.login(email=email, password="hunter2hunter2")
    return tenant.id, session.token


def _provision_tenant(slug: str) -> str:
    """Tenant created via the SDK (no auth needed) so tests can stage cross-
    tenant scenarios without minting an admin first."""
    return live_client.create_tenant(slug.title(), slug).id


def _cookies_for(token: str) -> dict[str, str]:
    return {"wapsell_session": token}


class TestListTenantsScoping:
    def test_tenant_user_sees_only_their_tenant(self, http: TestClient, auth_on: None) -> None:
        tid_a, token_a = _new_tenant_and_user(
            http, slug="authscope-a", email="a@scope.test", role=UserRole.TENANT
        )
        # A second tenant the user must NOT see.
        tid_b = _provision_tenant("authscope-b")

        res = http.get("/tenants", cookies=_cookies_for(token_a))
        assert res.status_code == 200
        slugs = [t["slug"] for t in res.json()]
        assert slugs == ["authscope-a"]
        assert "authscope-b" not in slugs

        # And the per-tenant lookup for B fails with 403, not 404 — distinction
        # matters so the dashboard can redirect rather than show "not found".
        res = http.get(f"/tenants/{tid_b}", cookies=_cookies_for(token_a))
        assert res.status_code == 403
        assert tid_a != tid_b

    def test_admin_user_sees_every_tenant(self, http: TestClient, auth_on: None) -> None:
        # Even after creating an admin-only listing scope, admin sees its own
        # tenant + every other tenant in the system.
        _, token = _new_tenant_and_user(
            http, slug="authscope-admin", email="admin@scope.test", role=UserRole.ADMIN
        )
        _provision_tenant("scope-other")
        res = http.get("/tenants", cookies=_cookies_for(token))
        assert res.status_code == 200
        slugs = {t["slug"] for t in res.json()}
        assert {"authscope-admin", "scope-other"}.issubset(slugs)

    def test_unauthenticated_listing_is_401(self, http: TestClient, auth_on: None) -> None:
        res = http.get("/tenants")
        assert res.status_code == 401


class TestSubresourceScoping:
    """A TENANT user opening someone else's /soul, /handoff, /catalog, etc.,
    must get 403 — not 404, not the data. ADMIN can open any of them."""

    def test_tenant_user_can_read_own_soul(self, http: TestClient, auth_on: None) -> None:
        tid, token = _new_tenant_and_user(
            http, slug="sub-own", email="own@scope.test", role=UserRole.TENANT
        )
        res = http.get(f"/tenants/{tid}/soul", cookies=_cookies_for(token))
        assert res.status_code == 200

    def test_tenant_user_cannot_read_other_soul(self, http: TestClient, auth_on: None) -> None:
        _, token_a = _new_tenant_and_user(
            http, slug="sub-mine", email="mine@scope.test", role=UserRole.TENANT
        )
        # Other tenant the user does NOT own.
        other_id = _provision_tenant("sub-other")
        res = http.get(f"/tenants/{other_id}/soul", cookies=_cookies_for(token_a))
        assert res.status_code == 403

    def test_tenant_user_cannot_send_to_other_buyer(self, http: TestClient, auth_on: None) -> None:
        # Same idea, hot endpoint: human takeover send.
        _, token_a = _new_tenant_and_user(
            http,
            slug="send-mine",
            email="sendmine@scope.test",
            role=UserRole.TENANT,
        )
        other_id = _provision_tenant("send-other")
        bid = "send-other:5491100000000"
        res = http.post(
            f"/tenants/{other_id}/conversations/{bid}/send",
            json={"text": "x", "pause_hours": 0},
            cookies=_cookies_for(token_a),
        )
        assert res.status_code == 403

    def test_admin_can_read_any_tenant_handoff(self, http: TestClient, auth_on: None) -> None:
        _, token = _new_tenant_and_user(
            http,
            slug="sub-admin",
            email="subadmin@scope.test",
            role=UserRole.ADMIN,
        )
        other_id = _provision_tenant("sub-admin-other")
        res = http.get(f"/tenants/{other_id}/handoff", cookies=_cookies_for(token))
        assert res.status_code == 200


class TestPrivilegedActions:
    def test_create_tenant_requires_admin(self, http: TestClient, auth_on: None) -> None:
        _, token = _new_tenant_and_user(
            http,
            slug="priv-tenant-user",
            email="priv@scope.test",
            role=UserRole.TENANT,
        )
        res = http.post(
            "/tenants",
            json={"name": "Forbidden", "slug": "priv-forbidden"},
            cookies=_cookies_for(token),
        )
        assert res.status_code == 403

    def test_create_tenant_works_for_admin(self, http: TestClient, auth_on: None) -> None:
        _, token = _new_tenant_and_user(
            http,
            slug="priv-admin-user",
            email="privadmin@scope.test",
            role=UserRole.ADMIN,
        )
        res = http.post(
            "/tenants",
            json={"name": "By Admin", "slug": "priv-by-admin"},
            cookies=_cookies_for(token),
        )
        assert res.status_code == 201

    def test_register_requires_admin(self, http: TestClient, auth_on: None) -> None:
        # Without a session at all — 401 → 403 either way is denial, what we
        # want is "not 201".
        res = http.post(
            "/auth/register",
            json={
                "email": "noauth@scope.test",
                "password": "hunter2hunter2",
                "role": "TENANT",
                "tenant_id": None,
            },
        )
        assert res.status_code in {401, 403}


class TestNoEnforceWhenFlagOff:
    """Sanity check: with the env unset, every guard is silent. The other
    test suites run with the flag off so we don't need to re-test the world
    here — one happy-path probe is enough."""

    def test_listing_open_when_flag_off(self, http: TestClient) -> None:
        # No fixture toggling — flag is unset.
        res = http.get("/tenants")
        assert res.status_code == 200
