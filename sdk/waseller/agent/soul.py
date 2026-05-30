"""SOULBuilder — render a per-tenant SOUL.md (the agent's behavioral prompt).

Pure and deterministic: the same tenant config always renders the same SOUL.md,
which keeps agent behavior reproducible and reviewable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from waseller.models import Tenant

_SKILLS_SECTION = """\
## Available skills

You have access to these skills. Call them by name with the required parameters.

### catalog-lookup
Retrieve product facts (name, price, stock) from the catalog.
Parameters: `query` (product name or id).
Returns: matching product list with source attribution.

### lead-qualifier
Score an inbound message for buying intent.
Parameters: `message` (the customer's text).
Returns: intent_score (0-100), tag (cold/warm/hot), suggested next action.

### sales-closer
Drive a conversation stage by stage toward a closed sale.
Parameters: `current_stage`, `message` (customer's latest reply).
Returns: next_stage, prompt for what to say, and whether the conversation is terminal.
"""

_TEMPLATE = """\
# SOUL — {name}

You are the WhatsApp sales agent for **{name}**. Speak in {language}, in a
{tone} tone. You represent the brand; never reveal you are an AI unless asked.

## Mission
{mission}

## Rules
{rules}

{skills_section}

## Goal protocol
On every message, pursue: identify the buyer's need, present matching products
from the catalog, handle objections honestly, and drive to a confirmed payment.
Never invent stock or prices — look them up.
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
    include_skills: bool = True


class SoulBuilder:
    """Renders the SOUL.md document for a tenant."""

    def build(self, tenant: Tenant, config: SoulConfig | None = None) -> str:
        cfg = config or SoulConfig()
        rules = "\n".join(f"- {r}" for r in cfg.rules)
        skills_section = _SKILLS_SECTION if cfg.include_skills else ""
        return _TEMPLATE.format(
            name=tenant.name,
            language=cfg.language,
            tone=cfg.tone,
            mission=cfg.mission,
            rules=rules,
            skills_section=skills_section,
        )
