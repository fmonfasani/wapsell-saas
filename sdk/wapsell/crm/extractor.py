"""CrmExtractor — read a conversation, return structured CRM updates.

This is the "moat" half of the CRM (Phase 2 of ``docs/PLAN-CRM.md``). The
recorder writes raw activities synchronously on every turn; the extractor
runs in a background task and uses gpt-4o-mini to mine the same turns for:

- ``contact_updates``  — field/value patches to the contact resource
                         (e.g. ``{"name": "María", "email": "m@x.com"}``)
- ``new_tasks``        — to-dos detected from the buyer's words ("agendá
                         para el martes" → task with ``due_at``)
- ``new_tags``         — labels the LLM thinks fit ("interesado_cuotas")
- ``stage_transition`` — kept as a hint for Phase 3 (deals); for now we
                         persist it as a tagged activity so nothing is lost

Design choices:

- **JSON-only output.** We instruct the model to return a single JSON
  object and call :func:`_extract_json_object` to tolerate the wrapper
  prose some models add ("Here is the JSON: ``{...}``"). On a parse
  failure we return an empty :class:`ExtractionResult` so the apply step
  is a clean no-op — never let a bad LLM answer crash the webhook.
- **Best-effort, never blocks.** The webhook dispatches an extractor run
  as ``asyncio.create_task`` after the reply has been delivered. Any
  exception inside ``extract()`` is logged + swallowed at the dispatcher
  level (see ``services/api/main.py``).
- **Idempotent apply.** :meth:`CrmExtractor.apply` writes to the same
  resources the recorder owns: contact patches go through ``upsert``,
  new tasks use a deterministic external_id derived from the contact +
  task title so re-running the extractor on the same window doesn't
  duplicate. Tasks already present in the contact's open-task list are
  skipped by title match.
- **Schema-light.** We don't validate every field shape — the dashboard
  treats LLM-extracted data as suggestions, badged "🤖 Auto" (Phase
  2.4 / PR #52). A field the LLM hallucinates is visible + editable; we
  optimize for recall, not precision.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
import json
import logging
import re
from typing import Any

from wapsell.crm.recorder import ACTIVITY_KIND
from wapsell.llm.port import LLMError, LLMMessage, LLMPort
from wapsell.resources.models import Resource
from wapsell.resources.repository import ResourceRepositoryPort

_log = logging.getLogger("wapsell.crm.extractor")

# Kind for the LLM-inferred to-do rows. New kind (not "activity") so the
# dashboard can list them in their own UI without filtering on `data.type`.
TASK_KIND = "task"

# Prefix marker on every LLM-created resource. Dashboard reads it to show
# the "🤖 Auto" badge + confirm/edit/delete buttons.
AUTO_SOURCE = "llm-extractor"

# Maximum turns we hand to the LLM. Past this we truncate (oldest first)
# to keep the prompt + cost bounded. 20 turns ≈ 600 input tokens at the
# average WhatsApp message length, well within gpt-4o-mini's window.
_MAX_TURNS = 20

# Maximum chars per task title we'll accept from the LLM — guards against
# a hallucinated multi-paragraph "title" blowing up the resource summary.
_MAX_TASK_TITLE_CHARS = 200


@dataclass(slots=True)
class ExtractedTask:
    """One to-do the LLM identified."""

    title: str
    due_at: str | None = None  # ISO 8601, best-effort; LLM may omit
    priority: str | None = None  # "low" | "med" | "high"; opaque otherwise


@dataclass(slots=True)
class StageTransition:
    """Held until Phase 3 has deals to update. We still surface this so the
    apply step can write it as an activity for audit."""

    from_stage: str | None
    to_stage: str
    reason: str | None = None


@dataclass(slots=True)
class ExtractionResult:
    """What :meth:`CrmExtractor.extract` returns. All fields default-empty
    so callers can treat partial extractions uniformly."""

    contact_updates: dict[str, Any] = field(default_factory=dict)
    new_tasks: list[ExtractedTask] = field(default_factory=list)
    new_tags: list[str] = field(default_factory=list)
    stage_transition: StageTransition | None = None

    @property
    def is_empty(self) -> bool:
        return (
            not self.contact_updates
            and not self.new_tasks
            and not self.new_tags
            and self.stage_transition is None
        )


@dataclass(slots=True)
class ConversationTurn:
    """One side of the chat — the LLM input is a list of these."""

    role: str  # "buyer" | "agent" | "human"
    text: str
    at: str | None = None  # ISO 8601, optional


_SYSTEM_PROMPT = """\
You are a CRM data extractor. Your input is a WhatsApp conversation
between a buyer and a sales agent (or a human operator). Your output is
a SINGLE JSON object describing CRM updates inferred from the conversation.

Output schema (all keys optional; omit a key when nothing applies):

{
  "contact_updates":  { "name": "...", "email": "...", "company": "...", "notes": "..." },
  "new_tasks":        [ { "title": "...", "due_at": "ISO-8601|null", "priority": "low|med|high" } ],
  "new_tags":         [ "string", ... ],
  "stage_transition": { "from": "...", "to": "...", "reason": "..." }
}

Rules:
- Return ONLY the JSON object, no prose, no markdown fences.
- "new_tasks" should capture commitments expressed by either side:
  "agendá para el martes", "te llamo mañana", "pasame el contrato el viernes".
  Convert relative dates to ISO 8601 when the conversation provides enough
  context; otherwise leave due_at null.
- "stage_transition.to" must be one of: new, qualified, scheduled,
  negotiating, closed_won, closed_lost.
- "new_tags" should be short kebab-case labels (e.g. "interesado-cuotas",
  "necesita-llamada-humana"). Avoid tags the operator already added.
- If the conversation has nothing CRM-relevant, return {}.
"""


class CrmExtractor:
    """Single-call LLM extractor + apply step.

    The extractor is stateless — one instance is shared across tenants
    (the LLM port + repository are passed in at construction time so the
    same wiring used by ``WapsellClient`` is reused)."""

    def __init__(
        self,
        *,
        llm: LLMPort,
        resources: ResourceRepositoryPort,
        model: str = "openai/gpt-4o-mini",
    ) -> None:
        self._llm = llm
        self._resources = resources
        self._model = model

    # ------------------------------------------------------------------
    # Extract
    # ------------------------------------------------------------------
    async def extract(self, turns: list[ConversationTurn]) -> ExtractionResult:
        """Call the LLM and parse the response. Failures yield an empty
        :class:`ExtractionResult` so the apply step is a clean no-op —
        callers can treat ``result.is_empty`` as "LLM had nothing to say
        OR errored", which is the right blast radius for a best-effort
        enrichment."""
        if not turns:
            return ExtractionResult()

        capped = turns[-_MAX_TURNS:]
        transcript = "\n".join(f"[{t.role}] {t.text}".strip() for t in capped if t.text.strip())
        if not transcript:
            return ExtractionResult()

        messages = [
            LLMMessage(role="system", content=_SYSTEM_PROMPT),
            LLMMessage(role="user", content=transcript),
        ]
        try:
            reply = await self._llm.complete(
                messages,
                model=self._model,
                # Low temperature: we want consistent extraction across
                # re-runs on the same window, not creative writing.
                temperature=0.1,
                max_tokens=512,
            )
        except LLMError as exc:
            _log.warning("crm extractor llm call failed: %s", str(exc)[:200])
            return ExtractionResult()

        return _parse_reply(reply.text)

    # ------------------------------------------------------------------
    # Apply
    # ------------------------------------------------------------------
    def apply(
        self,
        *,
        tenant_id: str,
        contact_id: str,
        result: ExtractionResult,
    ) -> None:
        """Persist the extracted updates. Idempotent: re-applying the same
        result is a no-op (or a no-change upsert)."""
        if result.is_empty:
            return

        contact = self._resources.get(contact_id)
        if contact is None or contact.tenant_id != tenant_id:
            # Race with delete or wrong tenant — quietly drop. The
            # extractor is best-effort; we don't recreate contacts here.
            _log.warning("crm extractor apply: contact %s not found", contact_id)
            return

        self._patch_contact(contact, result)
        self._write_tasks(tenant_id, contact_id, result.new_tasks)
        self._maybe_write_stage_activity(tenant_id, contact_id, result.stage_transition)

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _patch_contact(self, contact: Resource, result: ExtractionResult) -> None:
        """Merge contact_updates + new_tags into the contact resource."""
        data = dict(contact.data)
        changed = False

        for key, value in result.contact_updates.items():
            if not isinstance(key, str) or key in _PROTECTED_CONTACT_FIELDS:
                # Never let the LLM overwrite phone / external_id / counters.
                continue
            if data.get(key) == value:
                continue
            data[key] = value
            changed = True

        if result.new_tags:
            existing_tags = data.get("tags")
            tags_list = list(existing_tags) if isinstance(existing_tags, list) else []
            existing_set = set(tags_list)
            for tag in result.new_tags:
                normalized = tag.strip().lower()
                if normalized and normalized not in existing_set:
                    tags_list.append(normalized)
                    existing_set.add(normalized)
                    changed = True
            data["tags"] = tags_list

        if not changed:
            return

        updated = contact.model_copy(
            update={
                "data": data,
                "updated_at": _now(),
            }
        )
        self._resources.upsert(updated)

    def _write_tasks(
        self,
        tenant_id: str,
        contact_id: str,
        tasks: list[ExtractedTask],
    ) -> None:
        """Insert each new task. external_id is deterministic so reruns
        on the same window dedup; we also skip if an open task with the
        same normalized title already exists for this contact."""
        if not tasks:
            return

        existing_open_titles = self._open_task_titles(tenant_id, contact_id)

        for task in tasks:
            title = (task.title or "").strip()[:_MAX_TASK_TITLE_CHARS]
            if not title:
                continue
            key = _task_dedup_key(title)
            if key in existing_open_titles:
                continue
            ext_id = f"task:{contact_id}:{key}"
            data: dict[str, Any] = {
                "contact_id": contact_id,
                "title": title,
                "status": "open",
                "source": AUTO_SOURCE,
                "auto": True,
            }
            if task.due_at:
                data["due_at"] = task.due_at
            if task.priority:
                data["priority"] = task.priority

            resource = Resource(
                tenant_id=tenant_id,
                kind=TASK_KIND,
                external_id=ext_id,
                data=data,
                summary=title[:_MAX_TASK_TITLE_CHARS],
            )
            self._resources.upsert(resource)
            existing_open_titles.add(key)

    def _maybe_write_stage_activity(
        self,
        tenant_id: str,
        contact_id: str,
        transition: StageTransition | None,
    ) -> None:
        """Phase 3 will own a ``deal`` resource and apply the actual stage
        change; for now we just leave a breadcrumb activity so nothing is
        lost between Phase 2 ship and Phase 3 ship."""
        if transition is None:
            return
        summary = f"Stage → {transition.to_stage}"
        if transition.from_stage:
            summary = f"Stage {transition.from_stage} → {transition.to_stage}"
        data: dict[str, Any] = {
            "contact_id": contact_id,
            "type": "stage_transition",
            "from": transition.from_stage,
            "to": transition.to_stage,
            "reason": transition.reason,
            "source": AUTO_SOURCE,
            "auto": True,
            "at": _now().isoformat(),
        }
        # external_id couples to-stage + contact so re-running the
        # extractor on the same transition is a no-op upsert.
        resource = Resource(
            tenant_id=tenant_id,
            kind=ACTIVITY_KIND,
            external_id=f"stage:{contact_id}:{transition.to_stage}",
            data=data,
            summary=summary,
        )
        self._resources.upsert(resource)

    def _open_task_titles(self, tenant_id: str, contact_id: str) -> set[str]:
        """All open-task title keys for one contact, used to dedup."""
        keys: set[str] = set()
        # `list_for` is paginated by limit; tasks per contact stay small
        # (single-digit typical) so 1000 is comfortably enough.
        for resource in self._resources.list_for(tenant_id, kind=TASK_KIND, limit=1000):
            if resource.data.get("contact_id") != contact_id:
                continue
            if resource.data.get("status") != "open":
                continue
            title = str(resource.data.get("title", ""))
            if title:
                keys.add(_task_dedup_key(title))
        return keys


# --- helpers --------------------------------------------------------------


_PROTECTED_CONTACT_FIELDS: frozenset[str] = frozenset(
    {
        "phone",
        "first_contact_at",
        "last_seen_at",
        "turn_count",
        "source",
    }
)


def _now() -> datetime:
    return datetime.now(UTC)


def _task_dedup_key(title: str) -> str:
    """Normalize for the open-task dedup set — lowercase + collapse
    whitespace so "Llamar  María" and "llamar maría" hash the same."""
    return re.sub(r"\s+", " ", title.strip().lower())


_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json_object(text: str) -> dict[str, Any]:
    """Some models prefix the JSON with prose ("Here is the JSON: {...}")
    or wrap it in markdown fences. We greedily match the first ``{...}``
    span and parse that. Returns ``{}`` on any failure."""
    if not text:
        return {}
    stripped = text.strip()
    # Fast path — the model honored the "JSON only" instruction.
    try:
        parsed = json.loads(stripped)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        pass
    match = _JSON_OBJECT_RE.search(stripped)
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_reply(text: str) -> ExtractionResult:
    """Turn the LLM's raw text into an :class:`ExtractionResult`. Every
    branch tolerates missing / wrongly-typed keys — we never want a
    schema-strict failure to drop the entire extraction."""
    payload = _extract_json_object(text)
    if not payload:
        return ExtractionResult()

    contact_updates = payload.get("contact_updates")
    if not isinstance(contact_updates, dict):
        contact_updates = {}

    new_tasks: list[ExtractedTask] = []
    raw_tasks = payload.get("new_tasks")
    if isinstance(raw_tasks, list):
        for entry in raw_tasks:
            if not isinstance(entry, dict):
                continue
            title = entry.get("title")
            if not isinstance(title, str) or not title.strip():
                continue
            due = entry.get("due_at")
            priority = entry.get("priority")
            new_tasks.append(
                ExtractedTask(
                    title=title.strip(),
                    due_at=due if isinstance(due, str) and due.strip() else None,
                    priority=(priority if isinstance(priority, str) and priority.strip() else None),
                )
            )

    new_tags: list[str] = []
    raw_tags = payload.get("new_tags")
    if isinstance(raw_tags, list):
        for tag in raw_tags:
            if isinstance(tag, str) and tag.strip():
                new_tags.append(tag.strip())

    transition: StageTransition | None = None
    raw_trans = payload.get("stage_transition")
    if isinstance(raw_trans, dict):
        to_stage = raw_trans.get("to")
        if isinstance(to_stage, str) and to_stage.strip():
            from_stage = raw_trans.get("from")
            reason = raw_trans.get("reason")
            transition = StageTransition(
                from_stage=(
                    from_stage.strip()
                    if isinstance(from_stage, str) and from_stage.strip()
                    else None
                ),
                to_stage=to_stage.strip(),
                reason=(reason.strip() if isinstance(reason, str) and reason.strip() else None),
            )

    return ExtractionResult(
        contact_updates=contact_updates,
        new_tasks=new_tasks,
        new_tags=new_tags,
        stage_transition=transition,
    )
