"""LeadQualifierSkill — score and tag inbound leads.

Rule-based scoring using keyword signals. LLM-powered refinement lands in
a later phase; the deterministic baseline enables testability now.
"""

from __future__ import annotations

import re
from typing import Any

from wapsell.skills.base import SkillBase, SkillResult

_HIGH_INTENT = re.compile(
    r"\b(comprar|quiero|necesito|precio|cu[ée]nto|costo|envi[áa]r"
    r"|ordenar|pedir|pago|transferencia|urgente|hoy)\b",
    re.IGNORECASE,
)

_LOW_INTENT = re.compile(
    r"\b(solo|curiosidad|viendo|despu[eé]s|luego|tal vez|quiz[áa])\b",
    re.IGNORECASE,
)

_URGENCY = re.compile(
    r"\b(urgente|hoy|ahora|inmediato|ya|ma[ñn]ana|lo antes posible)\b",
    re.IGNORECASE,
)

_BUDGET = re.compile(
    r"\b(presupuesto|l[mm]ite|m[aá]ximo|no m[aá]s de|caro|barato|cuesta|cuesta)\b",
    re.IGNORECASE,
)

# Routing thresholds (0-100 intent_score scale).
_HOT_THRESHOLD = 70
_WARM_THRESHOLD = 40
_NURTURE_SCORE = 55


def _score(message: str) -> int:
    message = message.lower()
    score = 50
    high = len(_HIGH_INTENT.findall(message))
    low = len(_LOW_INTENT.findall(message))
    urgency = len(_URGENCY.findall(message))
    budget = len(_BUDGET.findall(message))
    score += high * 10
    score -= low * 8
    score += urgency * 15
    score += budget * 5
    return max(0, min(100, score))


def _tag(score: int) -> str:
    if score >= _HOT_THRESHOLD:
        return "hot"
    if score >= _WARM_THRESHOLD:
        return "warm"
    return "cold"


def _next_action(score: int, tag: str) -> str:
    if tag == "hot":
        return "prioritize: assign sales-closer immediately"
    if tag == "warm" and score >= _NURTURE_SCORE:
        return "nurture: send catalog and follow up"
    return "monitor: no immediate action"


class LeadQualifierSkill(SkillBase):
    """Score an inbound message for buying intent (0-100) and return a routing tag."""

    name = "lead-qualifier"

    async def execute(self, context: dict[str, Any], params: dict[str, Any]) -> SkillResult:
        message = (params.get("message") or "").strip()
        if not message:
            return SkillResult.fail("message is required")

        score = _score(message)
        tag = _tag(score)
        return SkillResult.ok(
            intent_score=score,
            tag=tag,
            urgency_detected=bool(_URGENCY.search(message)),
            budget_signal_detected=bool(_BUDGET.search(message)),
            suggested_next_action=_next_action(score, tag),
        )
