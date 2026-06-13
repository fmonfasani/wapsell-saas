"""Tests for the background CRM-extractor dispatcher (PR #52).

We monkeypatch the module-level ``_crm_extractor`` so the dispatcher
actually fires; in normal test runs it's None (no MP credentials, no
LLM key) and the helper short-circuits.
"""

from __future__ import annotations

import asyncio

import pytest
from services.api import main as api_module

from wapsell.crm import ConversationTurn, ExtractionResult
from wapsell.memory.buyer import BuyerInteraction, InMemoryBuyerMemory
from wapsell.resources import InMemoryResourceRepository, Resource

pytestmark = pytest.mark.unit


# --- Helpers --------------------------------------------------------------


class _RecordingExtractor:
    """Captures (extract, apply) calls so we can assert what the
    dispatcher decided to do."""

    def __init__(
        self,
        *,
        result: ExtractionResult | None = None,
        raises_extract: Exception | None = None,
        raises_apply: Exception | None = None,
    ) -> None:
        self._result = result or ExtractionResult(new_tags=["x"])
        self._raises_extract = raises_extract
        self._raises_apply = raises_apply
        self.extract_calls: list[list[ConversationTurn]] = []
        self.apply_calls: list[tuple[str, str, ExtractionResult]] = []

    async def extract(self, turns: list[ConversationTurn]) -> ExtractionResult:
        if self._raises_extract:
            raise self._raises_extract
        self.extract_calls.append(list(turns))
        return self._result

    def apply(self, *, tenant_id: str, contact_id: str, result: ExtractionResult) -> None:
        if self._raises_apply:
            raise self._raises_apply
        self.apply_calls.append((tenant_id, contact_id, result))


@pytest.fixture
def isolate_extractor(monkeypatch: pytest.MonkeyPatch) -> InMemoryResourceRepository:
    """Swap module-level state so the dispatcher runs against in-memory
    repos owned by the test, untouched by other suites. WapsellClient
    exposes ``resources`` / ``memory`` as read-only properties backed by
    underscore attrs, so we patch those directly."""
    repo = InMemoryResourceRepository()
    memory = InMemoryBuyerMemory()
    monkeypatch.setattr(api_module._client, "_resources", repo)
    monkeypatch.setattr(api_module._client, "_memory", memory)
    return repo


def _seed_contact(
    repo: InMemoryResourceRepository, *, tenant_id: str, phone: str, turn_count: int
) -> Resource:
    return repo.upsert(
        Resource(
            tenant_id=tenant_id,
            kind="contact",
            external_id=f"buyer:{phone}",
            data={"phone": phone, "turn_count": turn_count},
            summary=f"+{phone}",
        )
    )


# --- Dispatcher gating ----------------------------------------------------


class TestDispatcherGating:
    def test_noop_when_extractor_is_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Default state: _crm_extractor is None in the test env.
        monkeypatch.setattr(api_module, "_crm_extractor", None)
        # Should not raise and should not create a task.
        api_module._maybe_dispatch_crm_extractor(
            tenant_id="t1", buyer_id="t1:549110000999", from_number="549110000999"
        )

    def test_stride_skips_non_multiples(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolate_extractor: InMemoryResourceRepository,
    ) -> None:
        recorder = _RecordingExtractor()
        monkeypatch.setattr(api_module, "_crm_extractor", recorder)
        monkeypatch.setattr(
            "os.environ",
            {**__import__("os").environ, "WAPSELL_CRM_EXTRACTOR_STRIDE": "3"},
        )
        # turn_count=2 → 2 % 3 == 2 ≠ 0 → skipped.
        _seed_contact(
            isolate_extractor,
            tenant_id="t1",
            phone="549110000301",
            turn_count=2,
        )
        api_module._maybe_dispatch_crm_extractor(
            tenant_id="t1",
            buyer_id="t1:549110000301",
            from_number="549110000301",
        )
        assert recorder.extract_calls == []

    @pytest.mark.asyncio
    async def test_runs_when_stride_matches(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolate_extractor: InMemoryResourceRepository,
    ) -> None:
        recorder = _RecordingExtractor(
            result=ExtractionResult(new_tags=["x"]),
        )
        monkeypatch.setattr(api_module, "_crm_extractor", recorder)
        monkeypatch.setattr(
            "os.environ",
            {**__import__("os").environ, "WAPSELL_CRM_EXTRACTOR_STRIDE": "3"},
        )
        contact = _seed_contact(
            isolate_extractor,
            tenant_id="t1",
            phone="549110000302",
            turn_count=3,
        )
        # Need some recall content so the extractor sees turns.
        await api_module._client.memory.remember(
            "t1:549110000302",
            BuyerInteraction(text="hola", role="buyer"),
        )
        api_module._maybe_dispatch_crm_extractor(
            tenant_id="t1",
            buyer_id="t1:549110000302",
            from_number="549110000302",
        )
        # Yield so the create_task scheduled coroutine gets to run.
        for _ in range(5):
            await asyncio.sleep(0)
        assert len(recorder.extract_calls) == 1
        assert recorder.apply_calls[0][0] == "t1"
        assert recorder.apply_calls[0][1] == contact.id

    def test_unknown_contact_short_circuits_without_dispatch(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolate_extractor: InMemoryResourceRepository,
    ) -> None:
        recorder = _RecordingExtractor()
        monkeypatch.setattr(api_module, "_crm_extractor", recorder)
        monkeypatch.setattr(
            "os.environ",
            {**__import__("os").environ, "WAPSELL_CRM_EXTRACTOR_STRIDE": "3"},
        )
        # No contact exists → no dispatch.
        api_module._maybe_dispatch_crm_extractor(
            tenant_id="t1",
            buyer_id="t1:549110000303",
            from_number="549110000303",
        )
        assert recorder.extract_calls == []


# --- Error swallowing -----------------------------------------------------


class TestErrorSwallowing:
    @pytest.mark.asyncio
    async def test_extract_failure_does_not_propagate(
        self,
        monkeypatch: pytest.MonkeyPatch,
        isolate_extractor: InMemoryResourceRepository,
    ) -> None:
        recorder = _RecordingExtractor(raises_extract=RuntimeError("boom"))
        monkeypatch.setattr(api_module, "_crm_extractor", recorder)
        monkeypatch.setattr(
            "os.environ",
            {**__import__("os").environ, "WAPSELL_CRM_EXTRACTOR_STRIDE": "0"},
        )
        _seed_contact(
            isolate_extractor,
            tenant_id="t1",
            phone="549110000304",
            turn_count=1,
        )
        await api_module._client.memory.remember(
            "t1:549110000304",
            BuyerInteraction(text="hola", role="buyer"),
        )
        # Should not raise.
        await api_module._run_crm_extractor(
            tenant_id="t1",
            buyer_id="t1:549110000304",
            from_number="549110000304",
        )
        # Apply never called because extract failed.
        assert recorder.apply_calls == []
