"""Tests for the auth subsystem (users, sessions, AuthService) + the
HTTP endpoints (/auth/login, /auth/logout, /auth/me, /auth/register).

Unit-scoped: in-memory repositories, no Postgres needed.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from services.api.main import _AUTH_COOKIE, app

from wapsell.auth import (
    AuthError,
    AuthService,
    InMemorySessionRepository,
    InMemoryUserRepository,
)
from wapsell.models import UserRole

pytestmark = pytest.mark.unit


@pytest.fixture
def auth() -> AuthService:
    return AuthService(
        users=InMemoryUserRepository(),
        sessions=InMemorySessionRepository(),
    )


@pytest.fixture
def http(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # TestClient runs on plain HTTP (http://testserver), so the default
    # `secure=True` flag makes the browser drop the session cookie. Disable
    # it for the duration of each test.
    monkeypatch.setenv("WAPSELL_AUTH_COOKIE_SECURE", "false")
    return TestClient(app)


# ---------------------------------------------------------------------------
# AuthService unit tests
# ---------------------------------------------------------------------------


class TestRegister:
    def test_register_returns_user_with_hashed_password(self, auth: AuthService) -> None:
        u = auth.register(email="a@b.com", password="passphrase-1")
        assert u.email == "a@b.com"
        # bcrypt hashes start with $2b$ or $2a$
        assert u.password_hash.startswith("$2")
        # And it's definitely not the plain text.
        assert u.password_hash != "passphrase-1"

    def test_email_is_lowercased(self, auth: AuthService) -> None:
        u = auth.register(email="MIXED@Case.COM", password="passphrase-1")
        assert u.email == "mixed@case.com"

    def test_duplicate_email_case_insensitive_raises(self, auth: AuthService) -> None:
        auth.register(email="a@b.com", password="passphrase-1")
        with pytest.raises(AuthError, match="email already exists"):
            auth.register(email="A@B.com", password="passphrase-1")

    def test_short_password_raises(self, auth: AuthService) -> None:
        with pytest.raises(AuthError, match="at least 8"):
            auth.register(email="x@y.com", password="short")

    def test_invalid_email_raises(self, auth: AuthService) -> None:
        with pytest.raises(AuthError, match="email"):
            auth.register(email="not-an-email", password="passphrase-1")

    def test_role_and_tenant_id_persist(self, auth: AuthService) -> None:
        u = auth.register(
            email="t@t.com",
            password="passphrase-1",
            role=UserRole.TENANT,
            tenant_id="tenant-xyz",
        )
        assert u.role is UserRole.TENANT
        assert u.tenant_id == "tenant-xyz"


# ---------------------------------------------------------------------------
# Login / logout / authenticate
# ---------------------------------------------------------------------------


class TestLogin:
    def test_correct_credentials_return_user_and_session(self, auth: AuthService) -> None:
        auth.register(email="a@b.com", password="passphrase-1")
        user, session = auth.login(email="a@b.com", password="passphrase-1")
        assert user.email == "a@b.com"
        assert session.user_id == user.id
        # 64 hex chars = 32 random bytes
        assert len(session.token) == 64
        assert session.expires_at > datetime.now(UTC)

    def test_wrong_password_raises(self, auth: AuthService) -> None:
        auth.register(email="a@b.com", password="passphrase-1")
        with pytest.raises(AuthError, match="invalid"):
            auth.login(email="a@b.com", password="wrong-password")

    def test_unknown_email_raises_with_same_message(self, auth: AuthService) -> None:
        # Same message as wrong-password so callers can't enumerate accounts.
        with pytest.raises(AuthError, match="invalid email or password"):
            auth.login(email="ghost@nowhere.com", password="passphrase-1")

    def test_login_is_case_insensitive_on_email(self, auth: AuthService) -> None:
        auth.register(email="a@b.com", password="passphrase-1")
        user, _ = auth.login(email="A@B.COM", password="passphrase-1")
        assert user.email == "a@b.com"


class TestAuthenticate:
    def test_valid_token_returns_user(self, auth: AuthService) -> None:
        auth.register(email="a@b.com", password="passphrase-1")
        _, session = auth.login(email="a@b.com", password="passphrase-1")
        u = auth.authenticate(session.token)
        assert u.email == "a@b.com"

    def test_missing_token_raises(self, auth: AuthService) -> None:
        with pytest.raises(AuthError, match="not authenticated"):
            auth.authenticate(None)
        with pytest.raises(AuthError, match="not authenticated"):
            auth.authenticate("")

    def test_unknown_token_raises(self, auth: AuthService) -> None:
        with pytest.raises(AuthError, match="session not found"):
            auth.authenticate("not-a-real-token")

    def test_expired_session_raises_and_is_purged(self) -> None:
        # Negative duration → expires_at lands strictly before now(), so the
        # `expires_at <= now()` check is unambiguous on any clock resolution.
        svc = AuthService(
            users=InMemoryUserRepository(),
            sessions=InMemorySessionRepository(),
            session_duration=timedelta(seconds=-1),
        )
        svc.register(email="a@b.com", password="passphrase-1")
        _, session = svc.login(email="a@b.com", password="passphrase-1")
        with pytest.raises(AuthError, match="expired"):
            svc.authenticate(session.token)
        # And the session row is gone — a re-attempt with the same token is now
        # a "session not found" error, not "expired" again.
        with pytest.raises(AuthError, match="session not found"):
            svc.authenticate(session.token)


class TestLogout:
    def test_logout_deletes_session(self, auth: AuthService) -> None:
        auth.register(email="a@b.com", password="passphrase-1")
        _, session = auth.login(email="a@b.com", password="passphrase-1")
        assert auth.logout(session.token) is True
        # Subsequent authenticate fails.
        with pytest.raises(AuthError, match="session not found"):
            auth.authenticate(session.token)

    def test_logout_unknown_token_returns_false_no_raise(self, auth: AuthService) -> None:
        assert auth.logout("ghost-token") is False


# ---------------------------------------------------------------------------
# HTTP endpoints
# ---------------------------------------------------------------------------


class TestAuthHTTP:
    def _register(self, http: TestClient, email: str, password: str) -> None:
        # Helper that bypasses ordering inside the test methods.
        http.post(
            "/auth/register",
            json={"email": email, "password": password},
        )

    def test_register_returns_201_and_user(self, http: TestClient) -> None:
        res = http.post(
            "/auth/register",
            json={"email": "create@example.com", "password": "passphrase-1"},
        )
        assert res.status_code == 201
        body = res.json()
        assert body["email"] == "create@example.com"
        assert body["role"] == "TENANT"

    def test_register_duplicate_returns_409(self, http: TestClient) -> None:
        http.post(
            "/auth/register",
            json={"email": "dup@example.com", "password": "passphrase-1"},
        )
        res = http.post(
            "/auth/register",
            json={"email": "DUP@example.com", "password": "passphrase-1"},
        )
        assert res.status_code == 409

    def test_register_short_password_returns_422(self, http: TestClient) -> None:
        res = http.post(
            "/auth/register",
            json={"email": "x@y.com", "password": "short"},
        )
        assert res.status_code == 422

    def test_login_sets_session_cookie(self, http: TestClient) -> None:
        self._register(http, "login@example.com", "passphrase-1")
        res = http.post(
            "/auth/login",
            json={"email": "login@example.com", "password": "passphrase-1"},
        )
        assert res.status_code == 200
        # Cookie was set with the expected name.
        assert _AUTH_COOKIE in res.cookies
        token = res.cookies[_AUTH_COOKIE]
        assert len(token) == 64

    def test_login_wrong_password_returns_401(self, http: TestClient) -> None:
        self._register(http, "wrong@example.com", "passphrase-1")
        res = http.post(
            "/auth/login",
            json={"email": "wrong@example.com", "password": "definitely-not"},
        )
        assert res.status_code == 401

    def test_me_with_cookie_returns_user(self, http: TestClient) -> None:
        self._register(http, "me@example.com", "passphrase-1")
        http.post(
            "/auth/login",
            json={"email": "me@example.com", "password": "passphrase-1"},
        )
        res = http.get("/auth/me")
        assert res.status_code == 200
        assert res.json()["email"] == "me@example.com"

    def test_me_without_cookie_returns_401(self, http: TestClient) -> None:
        # New TestClient → no cookies inherited from previous tests.
        fresh = TestClient(app)
        res = fresh.get("/auth/me")
        assert res.status_code == 401

    def test_logout_clears_cookie_and_invalidates_session(self, http: TestClient) -> None:
        self._register(http, "out@example.com", "passphrase-1")
        http.post(
            "/auth/login",
            json={"email": "out@example.com", "password": "passphrase-1"},
        )
        # Confirm we're logged in first.
        assert http.get("/auth/me").status_code == 200

        out = http.post("/auth/logout")
        assert out.status_code == 204

        # The cookie was cleared client-side; subsequent /me is 401.
        assert http.get("/auth/me").status_code == 401
