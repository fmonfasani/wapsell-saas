"""Inbox subsystem — bot pause registry for human takeover.

When a human agent grabs a thread, the bot has to step back. This module
owns the bookkeeping for that: which (tenant, buyer) pairs are currently
muted, until when, and the port shape so we can swap in-memory ↔ postgres
without touching the agent loop or webhook handler.

Why a separate module (not a column on the buyer interactions table or a
flag on the tenant): pauses are time-bounded, per-buyer, and need a hot
read path (every inbound webhook checks it). Co-locating it would force
either a join per turn or a buyer-table touch we don't want.
"""

from __future__ import annotations

from waseller.inbox.repository import (
    BotPause,
    BotPausePort,
    InMemoryBotPauseRepository,
    PostgresBotPauseRepository,
)

__all__ = [
    "BotPause",
    "BotPausePort",
    "InMemoryBotPauseRepository",
    "PostgresBotPauseRepository",
]
