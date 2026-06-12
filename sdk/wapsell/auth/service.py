"""High-level auth service. HTTP-agnostic; the FastAPI layer (services/api)
turns AuthService results into cookies and 401s."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import secrets

import bcrypt

from wapsell.auth.repository import SessionRepositoryPort, UserRepositoryPort
from wapsell.models import Session, User, UserRole

# 7 days is the standard "remember me" balance — short enough that a leaked
# session expires before most attackers exploit it, long enough that customers
# don't have to re-login every working day.
DEFAULT_SESSION_DURATION = timedelta(days=7)

# RFC-aligned email/password bounds. Extracted as constants so ruff's PLR2004
# (magic-value) check stays happy and the policy is reviewable in one place.
_MAX_EMAIL_LENGTH = 254
_MIN_PASSWORD_LENGTH = 8
_MAX_PASSWORD_LENGTH = 128  # bcrypt itself caps at 72 bytes; we cap at 128 chars


class AuthError(Exception):
    """Any auth failure visible to the user. The HTTP layer maps this to 401
    with the message verbatim — keep the message safe to display."""


class AuthService:
    """Register / login / logout / validate.

    Stateless instance: every method takes whatever it needs and writes to
    the repositories. No mutable in-memory state on the service itself, so
    sharing one instance across the api process is safe.
    """

    def __init__(
        self,
        *,
        users: UserRepositoryPort,
        sessions: SessionRepositoryPort,
        session_duration: timedelta = DEFAULT_SESSION_DURATION,
    ) -> None:
        self._users = users
        self._sessions = sessions
        self._session_duration = session_duration

    # ---- registration ------------------------------------------------------

    def register(
        self,
        *,
        email: str,
        password: str,
        role: UserRole = UserRole.TENANT,
        tenant_id: str | None = None,
    ) -> User:
        """Create a new user. Raises AuthError on duplicate email."""
        self._validate_email(email)
        self._validate_password(password)
        password_hash = _hash_password(password)
        user = User(
            email=email.strip().lower(),
            password_hash=password_hash,
            role=role,
            tenant_id=tenant_id,
        )
        try:
            return self._users.add(user)
        except ValueError as exc:
            # Underlying repository surfaced a duplicate-email; reframe as
            # auth error so the caller maps to 409.
            raise AuthError(str(exc)) from exc

    # ---- login / logout ----------------------------------------------------

    def login(self, *, email: str, password: str) -> tuple[User, Session]:
        """Verify credentials and create a fresh session. Returns the (user,
        session) pair so the HTTP layer can set both the cookie (with
        session.token) and pre-load tenant context (from user)."""
        user = self._users.by_email(email.strip().lower())
        # Constant-ish-time on the miss path: still call bcrypt against a
        # fixed dummy hash so a missing-email response time can't be
        # distinguished from a wrong-password one. Defensive but cheap.
        if user is None:
            _verify_password(password, _DUMMY_BCRYPT_HASH)
            raise AuthError("invalid email or password")
        if not _verify_password(password, user.password_hash):
            raise AuthError("invalid email or password")

        session = Session(
            token=_new_session_token(),
            user_id=user.id,
            expires_at=datetime.now(UTC) + self._session_duration,
        )
        self._sessions.add(session)
        return user, session

    def logout(self, token: str) -> bool:
        """Drop the session. Returns False if it didn't exist (idempotent)."""
        return self._sessions.delete(token)

    # ---- session validation -----------------------------------------------

    def authenticate(self, token: str | None) -> User:
        """Return the user behind a session token or raise AuthError. The
        HTTP layer wraps this into a dependency that issues a 401."""
        if not token:
            raise AuthError("not authenticated")
        session = self._sessions.get(token)
        if session is None:
            raise AuthError("session not found")
        if session.expires_at <= datetime.now(UTC):
            # Expired: drop it so a re-login starts clean.
            self._sessions.delete(token)
            raise AuthError("session expired")
        user = self._users.get(session.user_id)
        if user is None:
            # User was deleted but session was not — clean up.
            self._sessions.delete(token)
            raise AuthError("user no longer exists")
        return user

    # ---- validation helpers -----------------------------------------------

    @staticmethod
    def _validate_email(email: str) -> None:
        e = email.strip()
        if "@" not in e or "." not in e.split("@")[-1]:
            raise AuthError("email looks invalid")
        if len(e) > _MAX_EMAIL_LENGTH:
            raise AuthError("email too long")

    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password) < _MIN_PASSWORD_LENGTH:
            raise AuthError(f"password must be at least {_MIN_PASSWORD_LENGTH} characters")
        if len(password) > _MAX_PASSWORD_LENGTH:
            raise AuthError("password too long")


# ---------------------------------------------------------------------------
# bcrypt helpers
# ---------------------------------------------------------------------------

# Pre-computed once so the wrong-email branch has the same bcrypt cost as
# the wrong-password branch. The hash itself is meaningless.
_DUMMY_BCRYPT_HASH = bcrypt.hashpw(b"dummy", bcrypt.gensalt(rounds=10)).decode()


def _hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt(rounds=12)).decode()


def _verify_password(password: str, stored_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), stored_hash.encode("utf-8"))
    except (ValueError, TypeError):
        # Malformed stored hash (shouldn't happen, but don't crash auth).
        return False


def _new_session_token() -> str:
    # 32 random bytes → 64 hex chars. Plenty of entropy; URL-safe enough for a
    # cookie value without quoting.
    return secrets.token_hex(32)
