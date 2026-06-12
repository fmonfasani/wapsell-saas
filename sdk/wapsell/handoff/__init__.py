"""Handoff (bot → human) subsystem.

When a buyer explicitly asks for a person, the agent should stop generating
and surface the conversation to a human seller — that's the whole feature.
The detector is intentionally keyword-based (not LLM-scored): explicit asks
like "quiero hablar con un humano" are the highest-precision signal and the
SDK pays nothing per turn for them. LLM-based sentiment scoring is left as
a follow-up if customer feedback shows keywords miss too many frustrated
buyers.

Exports:

- :class:`HandoffDetector` / :class:`HandoffDecision` — pure, sync, tested.
- :class:`HandoffNotifierPort` + adapters — out-of-band notify (webhook).
"""

from __future__ import annotations

from wapsell.handoff.detector import HandoffDecision, HandoffDetector
from wapsell.handoff.notifier import (
    HandoffNotifierPort,
    HttpHandoffNotifier,
    NullHandoffNotifier,
)

__all__ = [
    "HandoffDecision",
    "HandoffDetector",
    "HandoffNotifierPort",
    "HttpHandoffNotifier",
    "NullHandoffNotifier",
]
