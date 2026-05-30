"""SalesCloserSkill — deterministic conversation stage machine.

Drives a WhatsApp conversation through stages: IDENTIFY → PRESENT → OBJECTIONS
→ CONFIRM → NOTIFY. Each stage produces a suggested agent response and the
next possible transitions.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from hermesell.skills.base import SkillBase, SkillResult


class Stage(StrEnum):
    IDENTIFY = "IDENTIFY"
    PRESENT = "PRESENT"
    OBJECTIONS = "OBJECTIONS"
    CONFIRM = "CONFIRM"
    NOTIFY = "NOTIFY"
    CLOSED = "CLOSED"
    ESCALATED = "ESCALATED"


_STAGE_PROMPTS: dict[Stage, str] = {
    Stage.IDENTIFY: ("Preguntá al cliente qué producto busca, cantidad y uso."),
    Stage.PRESENT: (
        "Presentá los productos del catálogo que matchean su necesidad. "
        "Incluí precio y stock. Nunca inventes datos."
    ),
    Stage.OBJECTIONS: (
        "Respondé objeciones con honestidad. Ofrecé alternativas si no hay stock. "
        "Si la objeción se repite, escalá a humano."
    ),
    Stage.CONFIRM: (
        "Pedí confirmación de compra y método de pago. No marques como cerrado sin pago confirmado."
    ),
    Stage.NOTIFY: ("Confirmá la venta y notificá al canal correspondiente."),
}


def _transition(current: Stage, message: str) -> Stage:  # noqa: PLR0911 — state machine; explicit conditionals beat a lookup table here
    msg = message.lower()
    if current is Stage.IDENTIFY:
        return Stage.PRESENT
    if current is Stage.PRESENT:
        if any(w in msg for w in ["no", "caro", "otro", "alternativa"]):
            return Stage.OBJECTIONS
        return Stage.CONFIRM
    if current is Stage.OBJECTIONS:
        # Escalation signals win over generic buy signals: "quiero hablar con
        # un humano" must escalate even though it contains "quiero".
        if any(w in msg for w in ["escalar", "humano", "hablar con"]):
            return Stage.ESCALATED
        if any(w in msg for w in ["ok", "sí", "si", "compro", "quiero", "dame"]):
            return Stage.CONFIRM
        return Stage.OBJECTIONS
    if current is Stage.CONFIRM:
        if any(w in msg for w in ["pagado", "transferí", "ok", "listo"]):
            return Stage.NOTIFY
        return Stage.CONFIRM
    if current is Stage.NOTIFY:
        return Stage.CLOSED
    return current


class SalesCloserSkill(SkillBase):
    """State-machine driven sales closer. One step per invocation."""

    name = "sales-closer"

    async def execute(self, context: dict[str, Any], params: dict[str, Any]) -> SkillResult:
        current_raw = (params.get("current_stage") or "IDENTIFY").upper()
        try:
            current = Stage(current_raw)
        except ValueError:
            return SkillResult.fail(f"invalid stage: {current_raw}")

        message = params.get("message") or ""
        next_stage = _transition(current, message)

        return SkillResult.ok(
            current_stage=current.value,
            next_stage=next_stage.value,
            prompt=_STAGE_PROMPTS.get(next_stage, ""),
            is_terminal=next_stage in (Stage.CLOSED, Stage.ESCALATED),
            needs_escalation=next_stage is Stage.ESCALATED,
        )
