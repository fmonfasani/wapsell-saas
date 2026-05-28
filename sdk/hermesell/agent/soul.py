"""SOULBuilder — render a per-tenant SOUL.md (the agent's behavioral prompt).

Pure and deterministic: the same tenant config always renders the same SOUL.md,
which keeps agent behavior reproducible and reviewable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from hermesell.models import Tenant

_TEMPLATE = """\
# SOUL — {name}

You are the WhatsApp sales agent for **{name}**. Speak in {language}, in a
{tone} tone. You represent the brand; never reveal you are an AI unless asked.

## Mission
{mission}

## Rules
{rules}

## Goal protocol
On every message, pursue: identify the buyer's need, present matching products
from the catalog (use catalog-lookup), handle objections honestly, and drive to a
confirmed payment. Never invent stock or prices — look them up.
"""


@dataclass(frozen=True, slots=True)
class SoulConfig:
    language: str = "español"
    tone: str = "cercano y profesional"
    mission: str = "Vender los productos del catálogo y cerrar ventas por WhatsApp."
    rules: tuple[str, ...] = field(
        default_factory=lambda: (
            "Nunca inventes stock ni precios.",
            "Confirmá el pago antes de dar por cerrada una venta.",
            "Si no sabés algo, decilo y ofrecé escalarlo a un humano.",
        )
    )


class SoulBuilder:
    """Renders the SOUL.md document for a tenant."""

    def build(self, tenant: Tenant, config: SoulConfig | None = None) -> str:
        cfg = config or SoulConfig()
        rules = "\n".join(f"- {r}" for r in cfg.rules)
        return _TEMPLATE.format(
            name=tenant.name,
            language=cfg.language,
            tone=cfg.tone,
            mission=cfg.mission,
            rules=rules,
        )
