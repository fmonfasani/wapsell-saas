"""Debug logging and agent tracing for Wapsell SDK.

When debug=True on WapsellClient, every agent turn produces an AgentTrace
that captures what happened: memory recalled, facts found, skill invoked, etc.

Useful for:
- Understanding agent behavior
- Debugging why a reply was generated
- Auditing decision paths
- Cost analysis (which facts/models were used)
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

logger = logging.getLogger("wapsell")


@dataclass
class AgentTrace:
    """Complete audit trail of one agent turn.

    Captured when debug=True. Includes:
    - What memory was recalled
    - What catalog facts were found
    - Which skill was invoked
    - The LLM prompt and response
    - Latency and cost metrics
    """

    timestamp: datetime
    tenant_slug: str
    buyer_id: str
    buyer_message: str

    # Memory phase
    memory_recalled_turns: int = 0
    memory_context: dict[str, Any] = field(default_factory=dict)

    # RAG phase
    catalog_facts_found: list[str] = field(default_factory=list)
    facts_count: int = 0

    # Skill phase
    skill_invoked: str | None = None
    skill_confidence: float | None = None

    # LLM phase
    llm_model: str | None = None
    llm_prompt_tokens: int = 0
    llm_response_tokens: int = 0
    llm_temperature: float = 0.7

    # Agent response
    agent_reply: str = ""
    handoff_triggered: bool = False

    # Latency
    phase_latencies_ms: dict[str, float] = field(default_factory=dict)
    total_latency_ms: float = 0.0

    def pretty_print(self) -> str:
        """Human-readable trace for debugging."""
        lines = [
            f"\n{'='*70}",
            f"AGENT TRACE — {self.timestamp.isoformat()}",
            f"{'='*70}",
            f"Tenant: {self.tenant_slug}",
            f"Buyer: {self.buyer_id}",
            f"\n[BUYER] {self.buyer_message}",
            f"\n[MEMORY] Recalled {self.memory_recalled_turns} turns",
            f"  Context: {self.memory_context}",
            f"\n[RAG] Found {self.facts_count} catalog facts",
        ]

        if self.catalog_facts_found:
            for fact in self.catalog_facts_found[:3]:  # Show first 3
                lines.append(f"  - {fact[:60]}...")
            if len(self.catalog_facts_found) > 3:
                lines.append(f"  ... and {len(self.catalog_facts_found) - 3} more")

        lines.extend([
            f"\n[SKILL] {self.skill_invoked or 'none'} (confidence: {self.skill_confidence})",
            f"\n[LLM] {self.llm_model}",
            f"  Tokens: {self.llm_prompt_tokens} input + {self.llm_response_tokens} output",
            f"  Temperature: {self.llm_temperature}",
            f"\n[AGENT] {self.agent_reply}",
            f"\n[TIMING] Total {self.total_latency_ms:.0f}ms",
        ])

        if self.phase_latencies_ms:
            for phase, ms in self.phase_latencies_ms.items():
                lines.append(f"  {phase}: {ms:.0f}ms")

        if self.handoff_triggered:
            lines.append("\n[HANDOFF] Escalated to human")

        lines.append(f"{'='*70}\n")
        return "\n".join(lines)

    def log(self) -> None:
        """Write trace to logger."""
        logger.info(self.pretty_print())


def enable_debug_logging(level: int = logging.DEBUG) -> None:
    """Enable verbose logging for Wapsell.

    Example:
        >>> from wapsell.logging import enable_debug_logging
        >>> enable_debug_logging()
        >>> client = WapsellClient.local(debug=True)
    """
    handler = logging.StreamHandler()
    handler.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    handler.setFormatter(formatter)
    logger.addHandler(handler)
    logger.setLevel(level)
