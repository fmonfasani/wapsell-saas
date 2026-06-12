"""Message templates subsystem (WhatsApp Business templates)."""

from __future__ import annotations

from wapsell.templates.repository import (
    InMemoryTemplateRepository,
    PostgresTemplateRepository,
    TemplateRepositoryPort,
)

__all__ = [
    "InMemoryTemplateRepository",
    "PostgresTemplateRepository",
    "TemplateRepositoryPort",
]
