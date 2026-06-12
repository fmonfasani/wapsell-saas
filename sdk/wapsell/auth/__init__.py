"""Auth subsystem — users + sessions for the dashboard.

Surface kept minimal:
- :class:`UserRepositoryPort` / adapters — persistence of users.
- :class:`SessionRepositoryPort` / adapters — persistence of sessions.
- :class:`AuthService` — high-level register / login / logout / validate.

Password hashes are bcrypt-based; session tokens are 32 random bytes
hex-encoded; cookies are issued by the FastAPI layer (this module is
HTTP-agnostic).
"""

from __future__ import annotations

from wapsell.auth.repository import (
    InMemorySessionRepository,
    InMemoryUserRepository,
    PostgresSessionRepository,
    PostgresUserRepository,
    SessionRepositoryPort,
    UserRepositoryPort,
)
from wapsell.auth.service import AuthError, AuthService

__all__ = [
    "AuthError",
    "AuthService",
    "InMemorySessionRepository",
    "InMemoryUserRepository",
    "PostgresSessionRepository",
    "PostgresUserRepository",
    "SessionRepositoryPort",
    "UserRepositoryPort",
]
