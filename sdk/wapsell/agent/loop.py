"""AgentLoop — the single function that turns an inbound message into a reply.

Five stages, deterministic except for the LLM call:

  1. **Recall**: read the last ``history_turns`` interactions for this buyer.
  2. **RAG**: query Hindsight (tenant-scoped) for facts relevant to the message.
  3. **Compose**: build a ``[system, ...history, user]`` ``LLMMessage`` list with
     the SOUL prompt + a "Catalog facts" block + a "Recent conversation" block.
  4. **LLM**: call the port (``EchoLLM`` in dev, ``OpenRouterLLM`` in prod).
  5. **Return**: an :class:`AgentTurn` carrying the reply, the facts cited, and
     the model used. Callers persist the turn to memory — the loop is read-only
     w.r.t. memory so it stays trivially retryable.

This is the only place that knows how to assemble the prompt. Routing, retries,
and the WhatsApp gateway live outside.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from wapsell.agent.soul import SoulBuilder, SoulConfig
from wapsell.handoff.detector import HandoffDecision, HandoffDetector
from wapsell.ingestion.hindsight import HindsightPort
from wapsell.llm.port import LLMMessage, LLMPort
from wapsell.memory.buyer import BuyerInteraction, BuyerMemoryPort
from wapsell.models import Fact, Tenant
from wapsell.resources.learning import LearningService
from wapsell.resources.models import Resource
from wapsell.resources.repository import ResourceRepositoryPort

# Sentinel model name surfaced into ``AgentTurn.model`` when a handoff
# short-circuits the LLM call. Kept descriptive so audit logs and the
# dashboard make sense without consulting documentation.
HANDOFF_MODEL = "<handoff>"


@dataclass(frozen=True, slots=True)
class AgentTurn:
    """The output of one agent step. ``facts_cited`` is the RAG context that
    informed the reply — handy for audit + future inline citations.

    ``handoff`` is set when the per-tenant detector tripped: ``reply`` is
    then the configured handoff message (not LLM-generated), ``model`` is
    :data:`HANDOFF_MODEL`, and the webhook handler should fire the notifier.

    ``resources_cited`` (PR #41) is the structured slice of the catalog the
    agent loop pulled via :class:`ResourceRepositoryPort`.search. Different
    from ``facts_cited`` which is the Hindsight RAG text facts — both ride
    in the same prompt now, with Hindsight as fallback and resources as the
    primary structured source."""

    reply: str
    model: str
    facts_cited: tuple[Fact, ...] = ()
    history_used: int = 0
    handoff: HandoffDecision | None = None
    resources_cited: tuple[Resource, ...] = ()


class AgentLoop:
    """Compose SOUL + recent dialogue + RAG → LLM → reply.

    Args:
        memory: where to recall the buyer's prior turns from. Tenant scoping is
            the caller's responsibility (compose ``buyer_id`` via ``buyer_id_for``).
        hindsight: tenant-scoped fact store queried with the inbound text.
        llm: the model port. Default in :class:`WapsellClient` is
            :class:`EchoLLM` so nothing calls the network until explicitly wired.
        soul_builder: renders the per-tenant behavioral prompt.
        history_turns: how many recent interactions to include in the prompt.
        rag_top_k: max facts to retrieve from Hindsight per turn.
    """

    def __init__(
        self,
        *,
        memory: BuyerMemoryPort,
        hindsight: HindsightPort,
        llm: LLMPort,
        soul_builder: SoulBuilder | None = None,
        handoff_detector: HandoffDetector | None = None,
        learning: LearningService | None = None,
        resources: ResourceRepositoryPort | None = None,
        resource_kind: str | None = None,
        resource_top_k: int = 5,
        history_turns: int = 6,
        rag_top_k: int = 5,
    ) -> None:
        self._memory = memory
        self._hindsight = hindsight
        self._llm = llm
        self._soul = soul_builder or SoulBuilder()
        # Default detector is keyword-based; a tenant with handoff_config=None
        # or enabled=False trivially returns "no escalate".
        self._handoff = handoff_detector or HandoffDetector()
        # Learning service (PR #38): when present, the agent loop computes
        # catalog hints from discovered schema + top filter keys and feeds
        # them into the SOUL prompt on every turn. When None, the loop
        # behaves exactly as before — no hints injected, soul builder gets
        # an empty string.
        self._learning = learning
        # Structured catalog (PR #41): when present, the agent loop queries
        # the resources store with the buyer's message as free-text and
        # mixes the matches into the prompt under "## Catalog items". This
        # is the structured complement to Hindsight RAG — same buyer text
        # routes both queries. When None, the loop falls back to Hindsight
        # only (the pre-PR #41 behavior).
        self._resources = resources
        self._resource_kind = resource_kind
        self._resource_top_k = resource_top_k
        self._history_turns = history_turns
        self._rag_top_k = rag_top_k

    async def respond(
        self,
        tenant: Tenant,
        buyer_id: str,
        message: str,
        *,
        soul_config: SoulConfig | None = None,
    ) -> AgentTurn:
        # Detect first — if the buyer is asking for a human we skip the LLM
        # call entirely (faster, cheaper, and we trust the configured message
        # more than whatever the model would have written under pressure).
        decision = self._handoff.evaluate(message, tenant.handoff_config)
        if decision.escalate and tenant.handoff_config is not None:
            return AgentTurn(
                reply=tenant.handoff_config.handoff_message,
                model=HANDOFF_MODEL,
                handoff=decision,
            )
        history = await self._memory.recall(buyer_id, limit=self._history_turns)
        facts = self._hindsight.query(text=message, tenant_id=tenant.id, top_k=self._rag_top_k)
        # Structured catalog lookup — best-effort. Errors during search
        # never block the reply path (the loop falls back to Hindsight RAG
        # alone, the pre-PR-#41 behavior).
        resources: list[Resource] = []
        if self._resources is not None:
            try:
                resources = self._resources.search(
                    tenant.id,
                    query_text=message,
                    kind=self._resource_kind,
                    limit=self._resource_top_k,
                )
            except Exception:
                resources = []
        prompt = self._compose_prompt(tenant, history, facts, resources, message, soul_config)
        reply = await self._llm.complete(prompt, model=tenant.model)
        return AgentTurn(
            reply=reply.text,
            model=reply.model,
            facts_cited=tuple(facts),
            history_used=len(history),
            resources_cited=tuple(resources),
        )

    def _compose_prompt(
        self,
        tenant: Tenant,
        history: list[BuyerInteraction],
        facts: list[Fact],
        resources: list[Resource],
        message: str,
        soul_config: SoulConfig | None,
    ) -> list[LLMMessage]:
        # Learning hints — best-effort; the loop never fails because the
        # learning service couldn't compute. Empty string is the silent
        # fallback and SoulBuilder treats it the same as "no hints".
        hints = ""
        if self._learning is not None:
            try:
                hints = self._learning.render_soul_hints(tenant.id)
            except Exception:
                hints = ""
        soul = self._soul.build(tenant, soul_config, learning_hints=hints)
        rag_block = _render_facts_block(facts) if facts else ""
        resources_block = _render_resources_block(resources) if resources else ""
        system_parts = [soul]
        # Resources block ranks higher than facts in the prompt because
        # structured rows are more reliable for citation. Facts are
        # complementary context (notes, blog posts, FAQ).
        if resources_block:
            system_parts.append(resources_block)
        if rag_block:
            system_parts.append(rag_block)
        messages: list[LLMMessage] = [LLMMessage(role="system", content="\n\n".join(system_parts))]
        # Replay the recent dialogue as alternating user/assistant turns; the
        # LLM relies on this to maintain conversational coherence.
        for turn in history:
            role: Literal["assistant", "user"] = "assistant" if turn.role == "agent" else "user"
            messages.append(LLMMessage(role=role, content=turn.text))
        messages.append(LLMMessage(role="user", content=message))
        return messages


def _render_facts_block(facts: list[Fact]) -> str:
    lines = ["## Catalog facts (use only what's here; never invent prices or stock)"]
    for i, fact in enumerate(facts, start=1):
        # Source is preserved so the agent can cite ("según el catálogo …").
        lines.append(f"{i}. [{fact.source}] {fact.content}")
    return "\n".join(lines)


def _render_resources_block(resources: list[Resource]) -> str:
    """Render the structured resources into a Markdown block the LLM can quote
    field-by-field. Each item gets its external_id as a stable reference and
    the full ``data`` JSON so the model can pick whichever attributes the
    buyer asked about (price, neighborhood, surface_m2 — whatever's there)."""
    lines = [
        "## Catalog items (structured, source of truth — never invent fields)",
        "Each item has an `id` you can quote and a `data` dict with all available attributes.",
    ]
    for i, r in enumerate(resources, start=1):
        ref = r.external_id or r.id
        # The summary is the friendliest line for the LLM to lead with;
        # the data dict is the rest of the truth.
        summary = r.summary or ""
        data_compact = ", ".join(f"{k}: {v}" for k, v in r.data.items() if v is not None)
        lines.append(f"{i}. **{ref}** — {summary}")
        if data_compact:
            lines.append(f"   - {data_compact}")
    return "\n".join(lines)
