"""Tests for the recall → RAG → SOUL → LLM → reply loop."""

from __future__ import annotations

import pytest

from waseller.agent.loop import AgentLoop
from waseller.client import WasellerClient, buyer_id_for
from waseller.ingestion.hindsight import InMemoryHindsight
from waseller.llm import EchoLLM, LLMMessage, ScriptedLLM
from waseller.memory.buyer import BuyerInteraction, InMemoryBuyerMemory
from waseller.models import Fact, Tenant

pytestmark = pytest.mark.unit


def _tenant(slug: str = "demo", model: str = "anthropic/claude-3-haiku") -> Tenant:
    return Tenant(name="Demo Inc", slug=slug, model=model)


class TestAgentLoopComposition:
    async def test_system_prompt_contains_soul_and_no_facts_when_rag_empty(
        self,
    ) -> None:
        llm = ScriptedLLM(replies=["ok"])
        loop = AgentLoop(
            memory=InMemoryBuyerMemory(),
            hindsight=InMemoryHindsight(),
            llm=llm,
        )
        tenant = _tenant()
        await loop.respond(tenant, "demo:54911", "hola")

        system = llm.calls[0][0]
        assert system.role == "system"
        # SOUL is in the system message…
        assert "Demo Inc" in system.content
        # …but the facts block is omitted entirely when there are no hits.
        assert "Catalog facts" not in system.content

    async def test_includes_rag_facts_when_hindsight_has_matches(self) -> None:
        hs = InMemoryHindsight()
        hs.add_fact(
            Fact(
                tenant_id="t1",
                source="catalog.csv#3",
                content="Zapatillas Aqua: $19990, stock 12.",
            )
        )
        hs.add_fact(
            Fact(
                tenant_id="t1",
                source="catalog.csv#4",
                content="Remera Negra: $9990, stock 30.",
            )
        )
        # Tenant-mismatched fact must NOT leak in
        hs.add_fact(
            Fact(
                tenant_id="other-tenant",
                source="leak.csv",
                content="Zapatillas robadas: $1.",
            )
        )
        llm = ScriptedLLM(replies=["respuesta"])
        loop = AgentLoop(memory=InMemoryBuyerMemory(), hindsight=hs, llm=llm)
        # Tenant.id is the canonical key; create one with a specific id by
        # building it manually.
        tenant = Tenant(id="t1", name="Demo", slug="demo")

        # InMemoryHindsight is substring-based (PostgresHindsight does tsvector
        # tokenization); query a single token that's in the catalog content.
        turn = await loop.respond(tenant, "demo:1", "zapatillas")

        system = llm.calls[0][0]
        assert "Catalog facts" in system.content
        assert "Zapatillas Aqua" in system.content
        # Tenant scoping enforced by HindsightPort.query — no cross-tenant leak
        assert "Zapatillas robadas" not in system.content
        assert len(turn.facts_cited) == 1
        assert turn.facts_cited[0].source == "catalog.csv#3"

    async def test_history_replayed_as_user_assistant_alternation(self) -> None:
        mem = InMemoryBuyerMemory()
        bid = "demo:54911"
        await mem.remember(bid, BuyerInteraction(text="hola", role="buyer"))
        await mem.remember(bid, BuyerInteraction(text="hola! qué buscás?", role="agent"))
        await mem.remember(bid, BuyerInteraction(text="zapatillas", role="buyer"))
        await mem.remember(bid, BuyerInteraction(text="te muestro modelos", role="agent"))

        llm = ScriptedLLM(replies=["ok"])
        loop = AgentLoop(memory=mem, hindsight=InMemoryHindsight(), llm=llm)
        turn = await loop.respond(_tenant(), bid, "cuánto sale?")

        msgs = llm.calls[0]
        # [system, user, assistant, user, assistant, user(new)] — 6 total
        assert [m.role for m in msgs] == [
            "system",
            "user",
            "assistant",
            "user",
            "assistant",
            "user",
        ]
        assert msgs[-1].content == "cuánto sale?"
        # Agent → assistant role mapping is the contract that lets the LLM see
        # the conversation as it would on the wire.
        assert turn.history_used == 4

    async def test_uses_tenant_model_as_the_llm_model_arg(self) -> None:
        llm = ScriptedLLM(replies=["ok"])
        loop = AgentLoop(memory=InMemoryBuyerMemory(), hindsight=InMemoryHindsight(), llm=llm)
        tenant = _tenant(model="openai/gpt-4o-mini")
        turn = await loop.respond(tenant, "demo:1", "hola")
        assert turn.model == "openai/gpt-4o-mini"

    async def test_respect_history_turn_cap(self) -> None:
        mem = InMemoryBuyerMemory()
        bid = "demo:cap"
        for i in range(20):
            await mem.remember(
                bid, BuyerInteraction(text=f"msg-{i}", role="buyer" if i % 2 == 0 else "agent")
            )
        llm = ScriptedLLM(replies=["ok"])
        loop = AgentLoop(memory=mem, hindsight=InMemoryHindsight(), llm=llm, history_turns=4)
        turn = await loop.respond(_tenant(), bid, "nuevo")
        assert turn.history_used == 4
        # 1 system + 4 history + 1 new user = 6
        assert len(llm.calls[0]) == 6

    async def test_does_not_persist_to_memory(self) -> None:
        # The loop is intentionally read-only on memory; the webhook owns the
        # writes so retries on the same inbound message don't double-write.
        mem = InMemoryBuyerMemory()
        loop = AgentLoop(memory=mem, hindsight=InMemoryHindsight(), llm=ScriptedLLM(replies=["ok"]))
        await loop.respond(_tenant(), "demo:rw", "hola")
        assert await mem.recall("demo:rw") == []


class TestWasellerClientWiring:
    def test_default_llm_is_echo(self) -> None:
        client = WasellerClient()
        assert isinstance(client.llm, EchoLLM)

    def test_agent_uses_injected_llm(self) -> None:
        scripted = ScriptedLLM(replies=["from script"])
        client = WasellerClient(llm=scripted)
        assert client.llm is scripted

    async def test_end_to_end_through_client(self) -> None:
        scripted = ScriptedLLM(replies=["¡hola! con qué te puedo ayudar?"])
        client = WasellerClient(llm=scripted)
        tenant = client.create_tenant("E2E Shop", "e2e-shop")
        bid = buyer_id_for(tenant.slug, "5491100000000")
        turn = await client.agent.respond(tenant, bid, "tenés disponible?")
        assert turn.reply == "¡hola! con qué te puedo ayudar?"
        # And the system prompt rendered uses the live SOUL builder
        system: LLMMessage = scripted.calls[0][0]
        assert "E2E Shop" in system.content
