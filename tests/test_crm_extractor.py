"""Tests for the CRM LLM extractor (Phase 2 / PR #51).

The extractor depends on an LLMPort + a ResourceRepositoryPort. We use
ScriptedLLM (canned replies, no network) and InMemoryResourceRepository
(state survives the test, no DB) so the suite stays under a second.
"""

from __future__ import annotations

import pytest

from wapsell.crm import (
    AUTO_SOURCE,
    CONTACT_KIND,
    TASK_KIND,
    ConversationTurn,
    CrmExtractor,
    ExtractionResult,
    contact_external_id,
)
from wapsell.crm.extractor import _parse_reply
from wapsell.llm.port import LLMError, ScriptedLLM
from wapsell.resources.models import Resource
from wapsell.resources.repository import InMemoryResourceRepository

pytestmark = pytest.mark.unit


# --- Helpers --------------------------------------------------------------


def _make_contact(repo: InMemoryResourceRepository, tenant_id: str) -> Resource:
    """A baseline contact resource like the recorder would create."""
    contact = Resource(
        tenant_id=tenant_id,
        kind=CONTACT_KIND,
        external_id=contact_external_id("549110000001"),
        data={
            "phone": "549110000001",
            "turn_count": 2,
            "tags": ["nuevo"],
        },
        summary="+549110000001",
    )
    return repo.upsert(contact)


def _extractor(
    *,
    replies: list[str] | None = None,
    repo: InMemoryResourceRepository | None = None,
) -> tuple[CrmExtractor, ScriptedLLM, InMemoryResourceRepository]:
    repo = repo or InMemoryResourceRepository()
    llm = ScriptedLLM(replies=list(replies or []))
    ex = CrmExtractor(llm=llm, resources=repo, model="openai/gpt-4o-mini")
    return ex, llm, repo


# --- _parse_reply ---------------------------------------------------------


class TestParseReply:
    def test_pure_json(self) -> None:
        text = '{"new_tags": ["interesado-cuotas"]}'
        result = _parse_reply(text)
        assert result.new_tags == ["interesado-cuotas"]

    def test_json_wrapped_in_prose(self) -> None:
        text = 'Here is the JSON:\n```json\n{"new_tags": ["a"]}\n```\nThanks!'
        result = _parse_reply(text)
        assert result.new_tags == ["a"]

    def test_empty_string_returns_empty(self) -> None:
        assert _parse_reply("").is_empty

    def test_garbage_returns_empty(self) -> None:
        assert _parse_reply("not json at all").is_empty

    def test_array_root_returns_empty(self) -> None:
        # We expect a JSON OBJECT, not an array; an array root drops cleanly.
        assert _parse_reply("[1, 2, 3]").is_empty

    def test_task_without_title_is_dropped(self) -> None:
        text = '{"new_tasks": [{"due_at": "2026-07-01"}]}'
        result = _parse_reply(text)
        assert result.new_tasks == []

    def test_stage_transition_requires_to(self) -> None:
        text = '{"stage_transition": {"from": "new"}}'
        result = _parse_reply(text)
        assert result.stage_transition is None

    def test_full_extraction(self) -> None:
        text = """
        {
          "contact_updates": {"name": "María", "email": "m@x.com"},
          "new_tasks": [
            {"title": "Llamar María", "due_at": "2026-07-10T15:00:00", "priority": "high"}
          ],
          "new_tags": ["interesada"],
          "stage_transition": {"from": "new", "to": "qualified", "reason": "asked price"}
        }
        """
        result = _parse_reply(text)
        assert result.contact_updates == {"name": "María", "email": "m@x.com"}
        assert len(result.new_tasks) == 1
        assert result.new_tasks[0].title == "Llamar María"
        assert result.new_tasks[0].priority == "high"
        assert result.new_tags == ["interesada"]
        assert result.stage_transition is not None
        assert result.stage_transition.to_stage == "qualified"


# --- CrmExtractor.extract -------------------------------------------------


class TestExtract:
    @pytest.mark.asyncio
    async def test_empty_turns_short_circuits_without_llm_call(self) -> None:
        ex, llm, _ = _extractor()
        result = await ex.extract([])
        assert result.is_empty
        assert llm.calls == []

    @pytest.mark.asyncio
    async def test_calls_llm_with_capped_transcript(self) -> None:
        ex, llm, _ = _extractor(replies=['{"new_tags": ["x"]}'])
        # 25 turns — should be capped to 20.
        turns = [ConversationTurn(role="buyer", text=f"msg {i}") for i in range(25)]
        await ex.extract(turns)
        assert len(llm.calls) == 1
        user_msg = llm.calls[0][1].content
        assert "msg 24" in user_msg  # last turn kept
        assert "msg 0" not in user_msg  # earliest dropped (would be turn 0..4)
        assert "msg 4" not in user_msg

    @pytest.mark.asyncio
    async def test_llm_error_returns_empty_result(self) -> None:
        ex, _, _ = _extractor()  # empty replies → ScriptedLLM raises
        turns = [ConversationTurn(role="buyer", text="hola")]
        result = await ex.extract(turns)
        assert result.is_empty

    @pytest.mark.asyncio
    async def test_extract_returns_parsed_result(self) -> None:
        ex, _, _ = _extractor(
            replies=['{"contact_updates": {"name": "Sebas"}, "new_tags": ["pro"]}']
        )
        result = await ex.extract(
            [ConversationTurn(role="buyer", text="soy Sebas, dueño de la empresa")]
        )
        assert result.contact_updates == {"name": "Sebas"}
        assert result.new_tags == ["pro"]

    @pytest.mark.asyncio
    async def test_extract_strips_blank_turns(self) -> None:
        ex, llm, _ = _extractor(replies=["{}"])
        await ex.extract(
            [
                ConversationTurn(role="buyer", text="  "),
                ConversationTurn(role="agent", text=""),
                ConversationTurn(role="buyer", text="hola"),
            ]
        )
        user_msg = llm.calls[0][1].content
        assert user_msg.count("\n") == 0  # one effective turn
        assert "hola" in user_msg


# --- CrmExtractor.apply ---------------------------------------------------


class TestApplyContact:
    def test_empty_result_is_noop(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        original_updated_at = contact.updated_at
        ex.apply(tenant_id="t1", contact_id=contact.id, result=ExtractionResult())
        refreshed = repo.get(contact.id)
        assert refreshed is not None
        assert refreshed.updated_at == original_updated_at  # untouched

    def test_patches_contact_with_new_fields(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(contact_updates={"name": "María", "email": "m@x.com"}),
        )
        refreshed = repo.get(contact.id)
        assert refreshed is not None
        assert refreshed.data["name"] == "María"
        assert refreshed.data["email"] == "m@x.com"
        # Existing fields preserved.
        assert refreshed.data["phone"] == "549110000001"

    def test_protected_fields_cannot_be_overwritten(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(
                contact_updates={
                    "phone": "evil",
                    "turn_count": 9999,
                    "name": "ok",
                }
            ),
        )
        refreshed = repo.get(contact.id)
        assert refreshed is not None
        assert refreshed.data["phone"] == "549110000001"  # protected
        assert refreshed.data["turn_count"] == 2  # protected
        assert refreshed.data["name"] == "ok"  # allowed

    def test_appends_new_tags_without_duplicates(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(new_tags=["nuevo", "interesado", "INTERESADO"]),
        )
        refreshed = repo.get(contact.id)
        assert refreshed is not None
        assert refreshed.data["tags"] == ["nuevo", "interesado"]

    def test_unknown_contact_is_silent(self) -> None:
        repo = InMemoryResourceRepository()
        ex, _, _ = _extractor(repo=repo)
        # No exception, no exception-like return — best-effort.
        ex.apply(
            tenant_id="t1",
            contact_id="ghost",
            result=ExtractionResult(contact_updates={"name": "x"}),
        )

    def test_wrong_tenant_is_silent(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        ex.apply(
            tenant_id="evil",
            contact_id=contact.id,
            result=ExtractionResult(contact_updates={"name": "x"}),
        )
        refreshed = repo.get(contact.id)
        assert refreshed is not None
        assert "name" not in refreshed.data


class TestApplyTasks:
    def test_creates_task_resource(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        from wapsell.crm import ExtractedTask  # noqa: PLC0415

        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(
                new_tasks=[
                    ExtractedTask(
                        title="Llamar martes 10am",
                        due_at="2026-07-14T13:00:00+00:00",
                        priority="high",
                    )
                ]
            ),
        )
        tasks = repo.list_for("t1", kind=TASK_KIND, limit=10)
        assert len(tasks) == 1
        task = tasks[0]
        assert task.data["title"] == "Llamar martes 10am"
        assert task.data["due_at"] == "2026-07-14T13:00:00+00:00"
        assert task.data["priority"] == "high"
        assert task.data["source"] == AUTO_SOURCE
        assert task.data["auto"] is True
        assert task.data["contact_id"] == contact.id
        assert task.data["status"] == "open"

    def test_idempotent_on_rerun(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        from wapsell.crm import ExtractedTask  # noqa: PLC0415

        for _ in range(3):
            ex.apply(
                tenant_id="t1",
                contact_id=contact.id,
                result=ExtractionResult(new_tasks=[ExtractedTask(title="Llamar mañana")]),
            )
        tasks = repo.list_for("t1", kind=TASK_KIND, limit=10)
        assert len(tasks) == 1

    def test_task_skipped_if_open_one_already_exists(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        # Operator manually created a similar task already.
        repo.upsert(
            Resource(
                tenant_id="t1",
                kind=TASK_KIND,
                external_id="task:manual:1",
                data={
                    "contact_id": contact.id,
                    "title": "Llamar  María",
                    "status": "open",
                },
                summary="Llamar María",
            )
        )
        ex, _, _ = _extractor(repo=repo)
        from wapsell.crm import ExtractedTask  # noqa: PLC0415

        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(
                new_tasks=[ExtractedTask(title="LLAMAR María")]  # same normalized
            ),
        )
        tasks = repo.list_for("t1", kind=TASK_KIND, limit=10)
        assert len(tasks) == 1  # the original

    def test_empty_title_dropped(self) -> None:
        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        from wapsell.crm import ExtractedTask  # noqa: PLC0415

        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(new_tasks=[ExtractedTask(title="   ")]),
        )
        assert repo.list_for("t1", kind=TASK_KIND, limit=10) == []


class TestApplyStageTransition:
    def test_writes_breadcrumb_activity(self) -> None:
        from wapsell.crm import ACTIVITY_KIND, StageTransition  # noqa: PLC0415

        repo = InMemoryResourceRepository()
        contact = _make_contact(repo, "t1")
        ex, _, _ = _extractor(repo=repo)
        ex.apply(
            tenant_id="t1",
            contact_id=contact.id,
            result=ExtractionResult(
                stage_transition=StageTransition(
                    from_stage="new",
                    to_stage="qualified",
                    reason="asked price",
                )
            ),
        )
        activities = repo.list_for("t1", kind=ACTIVITY_KIND, limit=10)
        # Activities filtered down to this contact's stage events.
        stage_events = [a for a in activities if a.data.get("type") == "stage_transition"]
        assert len(stage_events) == 1
        assert stage_events[0].data["to"] == "qualified"
        assert stage_events[0].data["source"] == AUTO_SOURCE


# --- ScriptedLLM sanity ---------------------------------------------------


class TestErrorHandling:
    @pytest.mark.asyncio
    async def test_extract_after_llm_raises_returns_empty(self) -> None:
        class _BoomLLM:
            async def complete(self, *_args, **_kwargs):
                raise LLMError("boom")

        repo = InMemoryResourceRepository()
        ex = CrmExtractor(llm=_BoomLLM(), resources=repo)  # type: ignore[arg-type]
        result = await ex.extract([ConversationTurn(role="buyer", text="hola")])
        assert result.is_empty
