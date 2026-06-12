"""SOULBuilder — render a per-tenant SOUL.md (the agent's behavioral prompt).

Pure and deterministic: the same tenant config always renders the same SOUL.md,
which keeps agent behavior reproducible and reviewable.
"""

from __future__ import annotations

from waseller.models import SoulConfig, Tenant

# Re-export so existing callers (`from waseller.agent.soul import SoulConfig`)
# keep working. The class itself moved to models.py to break an import cycle
# between Tenant <-> SoulConfig — see the docstring on SoulConfig.
__all__ = ["SoulBuilder", "SoulConfig"]

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

{skills_section}{learning_section}

## Goal protocol
On every message, pursue: identify the buyer's need, present matching products
from the catalog, handle objections honestly, and drive to a confirmed payment.
Never invent stock or prices — look them up.
"""


class SoulBuilder:
    """Renders the SOUL.md document for a tenant."""

    def build(
        self,
        tenant: Tenant,
        config: SoulConfig | None = None,
        *,
        learning_hints: str = "",
    ) -> str:
        """Render SOUL.md for the tenant.

        ``learning_hints`` (optional) is an auto-generated Markdown block
        produced by :class:`waseller.resources.LearningService` — fields
        discovered in the tenant's catalog + the filter keys buyers most
        often use. The agent loop computes it once per turn and passes it
        here; the builder itself stays pure (no side effects, no IO)."""
        # Resolution order: explicit config arg > tenant's persisted config > defaults.
        # This lets a one-off render override a tenant's saved SOUL without
        # mutating it (preview from the dashboard, debug from the CLI, etc).
        cfg = config or tenant.soul_config or SoulConfig()
        rules = "\n".join(f"- {r}" for r in cfg.rules)
        skills_section = _SKILLS_SECTION if cfg.include_skills else ""
        # Sandwich the learning section with blank lines so the markdown
        # renders cleanly whether or not it's empty.
        learning_section = f"\n{learning_hints.strip()}\n" if learning_hints.strip() else ""
        return _TEMPLATE.format(
            name=tenant.name,
            language=cfg.language,
            tone=cfg.tone,
            mission=cfg.mission,
            rules=rules,
            skills_section=skills_section,
            learning_section=learning_section,
        )
