"""Message templates subsystem (WhatsApp Business templates)."""

from __future__ import annotations

from waseller.templates.repository import (
    InMemoryTemplateRepository,
    PostgresTemplateRepository,
    TemplateRepositoryPort,
)

__all__ = [
    "InMemoryTemplateRepository",
    "PostgresTemplateRepository",
    "TemplateRepositoryPort",
]
