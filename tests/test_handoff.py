"""Tests for the handoff (bot → human) subsystem.

Covers:
- :class:`HandoffDetector` evaluating the per-tenant config (disabled, keyword
  hit with accents, no hit, empty config) — pure & sync.
- :class:`AgentLoop` short-circuiting the LLM when the detector escalates,
  emitting an :class:`AgentTurn` carrying the decision.
- :class:`HttpHandoffNotifier` posting the JSON payload, skipping when
  webhook_url is unset, swallowing network errors.
"""

from __future__ import annotations

import httpx
import pytest

from wapsell.agent.loop import HANDOFF_MODEL, AgentLoop
from wapsell.handoff import (
    HandoffDecision,
    HandoffDetector,
    HttpHandoffNotifier,
    NullHandoffNotifier,
)
from wapsell.ingestion.hindsight import InMemoryHindsight
from wapsell.llm import ScriptedLLM
from wapsell.memory.buyer import InMemoryBuyerMemory
from wapsell.models import HandoffConfig, Tenant

pytestmark = pytest.mark.unit


def _tenant(handoff: HandoffConfig | None = None) -> Tenant:
    return Tenant(name="Demo Inc", slug="demo", handoff_config=handoff)


class TestHandoffDetector:
    def test_none_config_skips(self) -> None:
        decision = HandoffDetector().evaluate("hablar con un humano", None)
        assert decision.escalate is False
        assert decision.matched_keyword is None

    def test_disabled_config_skips(self) -> None:
        config = HandoffConfig(enabled=False, keywords=["humano"])
        decision = HandoffDetector().evaluate("hablar con un humano", config)
        assert decision.escalate is False

    def test_keyword_hit_escalates(self) -> None:
        config = HandoffConfig(enabled=True, keywords=["humano", "vendedor"])
        decision = HandoffDetector().evaluate("Quiero hablar con un vendedor.", config)
        assert decision.escalate is True
        assert decision.matched_keyword == "vendedor"

    def test_accent_insensitive(self) -> None:
        # Configured keyword has no accent; buyer types it with one. The
        # detector strips diacritics so the match still trips.
        config = HandoffConfig(enabled=True, keywords=["asesor"])
        decision = HandoffDetector().evaluate("Quiero un asésor por favor", config)
        assert decision.escalate is True
        assert decision.matched_keyword == "asesor"

    def test_case_insensitive(self) -> None:
        config = HandoffConfig(enabled=True, keywords=["agente humano"])
        decision = HandoffDetector().evaluate("Necesito un AGENTE Humano YA", config)
        assert decision.escalate is True

    def test_no_hit(self) -> None:
        config = HandoffConfig(enabled=True, keywords=["humano"])
        decision = HandoffDetector().evaluate("Hola, cuánto sale el modelo X?", config)
        assert decision.escalate is False

    def test_empty_keyword_skipped(self) -> None:
        # An accidental empty string in the keywords list must not match
        # every buyer message — that would escalate everything.
        config = HandoffConfig(enabled=True, keywords=["", "humano"])
        decision = HandoffDetector().evaluate("Hola, cuánto sale?", config)
        assert decision.escalate is False


class TestAgentLoopHandoff:
    async def test_escalation_short_circuits_llm(self) -> None:
        # ScriptedLLM with zero replies would explode if the loop reached the
        # LLM call — proving the loop took the handoff path.
        llm = ScriptedLLM(replies=[])
        loop = AgentLoop(memory=InMemoryBuyerMemory(), hindsight=InMemoryHindsight(), llm=llm)
        config = HandoffConfig(
            enabled=True,
            keywords=["humano"],
            handoff_message="Te paso con un compañero humano.",
        )
        turn = await loop.respond(_tenant(config), "demo:1", "Quiero hablar con un humano!")

        assert turn.reply == "Te paso con un compañero humano."
        assert turn.model == HANDOFF_MODEL
        assert turn.handoff is not None
        assert turn.handoff.escalate is True
        assert turn.handoff.matched_keyword == "humano"
        assert llm.calls == []

    async def test_no_escalation_reaches_llm(self) -> None:
        llm = ScriptedLLM(replies=["ok"])
        loop = AgentLoop(memory=InMemoryBuyerMemory(), hindsight=InMemoryHindsight(), llm=llm)
        config = HandoffConfig(enabled=True, keywords=["humano"])
        turn = await loop.respond(_tenant(config), "demo:1", "cuánto sale?")

        assert turn.reply == "ok"
        assert turn.handoff is None
        assert len(llm.calls) == 1

    async def test_config_disabled_reaches_llm(self) -> None:
        # Even though the buyer says "humano", enabled=False skips detection.
        llm = ScriptedLLM(replies=["respuesta del LLM"])
        loop = AgentLoop(memory=InMemoryBuyerMemory(), hindsight=InMemoryHindsight(), llm=llm)
        config = HandoffConfig(enabled=False, keywords=["humano"])
        turn = await loop.respond(_tenant(config), "demo:1", "hablar con un humano")

        assert turn.reply == "respuesta del LLM"
        assert turn.handoff is None


class TestHandoffNotifiers:
    async def test_null_notifier_is_noop(self) -> None:
        notifier = NullHandoffNotifier()
        # Just must not raise.
        await notifier.notify(
            tenant=_tenant(),
            buyer_id="demo:1",
            message="hablar con un humano",
            decision=HandoffDecision(escalate=True, matched_keyword="humano"),
        )

    async def test_http_notifier_skips_when_webhook_url_unset(self) -> None:
        # No httpx client touched because the notifier returns early.
        class _Boom:
            async def post(self, *args: object, **kwargs: object) -> None:
                raise AssertionError("must not POST when webhook_url is None")

        notifier = HttpHandoffNotifier(client=_Boom())  # type: ignore[arg-type]
        config = HandoffConfig(enabled=True, webhook_url=None)
        tenant = _tenant(config)
        await notifier.notify(
            tenant=tenant,
            buyer_id="demo:1",
            message="x",
            decision=HandoffDecision(escalate=True, matched_keyword="humano"),
        )

    async def test_http_notifier_posts_payload(self) -> None:
        captured: list[dict[str, object]] = []

        class _Resp:
            status_code = 200

        class _FakeClient:
            # Mirrors the kwargs the notifier passes to httpx.AsyncClient.post;
            # we accept **kwargs so the test isn't sensitive to whether the
            # notifier passes timeout positionally or as a kwarg.
            async def post(self, url: str, **kwargs: object) -> _Resp:
                captured.append({"url": url, **kwargs})
                return _Resp()

        notifier = HttpHandoffNotifier(client=_FakeClient())  # type: ignore[arg-type]
        config = HandoffConfig(enabled=True, webhook_url="https://hook.example/x")
        tenant = _tenant(config)
        await notifier.notify(
            tenant=tenant,
            buyer_id="demo:54911",
            message="Quiero un humano",
            decision=HandoffDecision(escalate=True, matched_keyword="humano"),
        )

        assert len(captured) == 1
        body = captured[0]["json"]
        assert isinstance(body, dict)
        assert body["event"] == "handoff.escalated"
        assert body["buyer_id"] == "demo:54911"
        assert body["matched_keyword"] == "humano"
        assert isinstance(body["tenant"], dict)
        assert body["tenant"]["slug"] == "demo"
        assert captured[0]["timeout"] == 5.0

    async def test_http_notifier_swallows_errors(self) -> None:
        class _Failing:
            async def post(self, *args: object, **kwargs: object) -> None:
                raise httpx.ConnectError("boom")

        notifier = HttpHandoffNotifier(client=_Failing())  # type: ignore[arg-type]
        config = HandoffConfig(enabled=True, webhook_url="https://hook.example/x")
        tenant = _tenant(config)
        # Must not raise — we don't want a flaky webhook to break replies.
        await notifier.notify(
            tenant=tenant,
            buyer_id="demo:1",
            message="x",
            decision=HandoffDecision(escalate=True, matched_keyword="humano"),
        )
