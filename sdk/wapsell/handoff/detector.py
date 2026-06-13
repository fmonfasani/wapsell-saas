"""Handoff detector — decides whether a buyer message should escalate to a human.

Pure, sync, deterministic. Substring keyword match on a lower-cased copy of
the buyer text, with diacritic stripping so "Quiero un Asésor" still trips
on "asesor". One match is enough — the detector returns on the first hit
to keep evaluation O(len(keywords)) in the common case.

Lives outside :mod:`wapsell.agent.loop` so the loop only sees a small port
and we can swap in (e.g.) an LLM-scored detector without touching the loop.
"""

from __future__ import annotations

from dataclasses import dataclass
import unicodedata

from wapsell.models import HandoffConfig


@dataclass(frozen=True, slots=True)
class HandoffDecision:
    """Result of one evaluation. ``matched_keyword`` is the configured form
    (case + accents preserved) of the keyword that tripped — surfaced into
    the turn metadata so the dashboard can show *why* it escalated."""

    escalate: bool
    matched_keyword: str | None = None

    @classmethod
    def skip(cls) -> HandoffDecision:
        return cls(escalate=False, matched_keyword=None)


class HandoffDetector:
    """Decides whether to escalate based on the buyer message + tenant config.

    No state. Safe to share across requests. The detector is intentionally
    permissive about ``config`` being ``None`` or ``enabled=False`` so the
    agent loop can call it unconditionally and trust the answer is "no".
    """

    def evaluate(self, message: str, config: HandoffConfig | None) -> HandoffDecision:
        if config is None or not config.enabled:
            return HandoffDecision.skip()
        normalized = _normalize(message)
        for keyword in config.keywords:
            needle = _normalize(keyword)
            if needle and needle in normalized:
                return HandoffDecision(escalate=True, matched_keyword=keyword)
        return HandoffDecision.skip()


def _normalize(text: str) -> str:
    """Lower-case + strip diacritics. So "Asésor" → "asesor", which matches
    a keyword "asesor" the tenant configured. Without this, a buyer typing
    accented Spanish would silently bypass detection."""
    decomposed = unicodedata.normalize("NFD", text)
    stripped = "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")
    return stripped.lower().strip()
