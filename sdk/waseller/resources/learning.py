"""Schema discovery + SOUL auto-enrichment — the learning loop (PR #38).

Two pure aggregations + one service that combines them:

- :func:`discover_schema` walks a sample of resources and tells you which
  fields appear, how often, with a few example values. The "schema" is
  emergent — there's no fixed model; the function infers what's there.
- :func:`top_filter_keys` aggregates the ``resource_query_log`` and tells
  you which fields buyers most often filter on. Strips ``max_`` / ``min_``
  prefixes so the range queries roll up to the underlying field.
- :class:`LearningService` packages both into :class:`LearningInsights`
  and renders a short Markdown hints block that the SOUL prompt can
  include. The agent's prompt then carries "this catalog has these
  fields: X, Y, Z; buyers most often filter on: A, B" without anyone
  having to type it.

The agent loop calls ``render_soul_hints`` on every turn. Cost is two
adapter calls (list_for + list_recent); both are O(N) over their input
and N is small for a single-tenant query (the dashboard caps both at
~200 rows). Cache only when this shows up in a perf profile.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from waseller.resources.repository import QueryLogPort, ResourceRepositoryPort


@dataclass(frozen=True, slots=True)
class FieldFrequency:
    """One field discovered in a resource sample."""

    name: str
    presence: float  # 0.0-1.0, fraction of sampled rows where the field appears
    example_values: tuple[str, ...]
    is_numeric: bool


@dataclass(frozen=True, slots=True)
class FilterFrequency:
    """One filter key the agent has used (range prefixes already stripped)."""

    key: str
    count: int


@dataclass(frozen=True, slots=True)
class LearningInsights:
    """Snapshot of what the resource store + query log can tell us about
    this tenant's catalog and how it's being used."""

    tenant_id: str
    sample_size: int
    window_days: int
    fields: tuple[FieldFrequency, ...]
    top_filters: tuple[FilterFrequency, ...]
    generated_at: datetime


_NUMERIC_THRESHOLD = 0.7  # field counts as numeric if ≥70% of values parse
_MAX_EXAMPLES_PER_FIELD = 4
_EXAMPLE_MAX_CHARS = 60
_DEFAULT_SAMPLE_SIZE = 50
_DEFAULT_DAYS_WINDOW = 30
_DEFAULT_TOP_FILTERS = 5
_MIN_PRESENCE_FOR_HINT = 0.25  # don't surface a field that's in <25% of rows


def discover_schema(
    resources: ResourceRepositoryPort,
    tenant_id: str,
    *,
    sample_size: int = _DEFAULT_SAMPLE_SIZE,
    kind: str | None = None,
) -> tuple[FieldFrequency, ...]:
    """Build a frequency table of the fields present in this tenant's
    resources. Returns ordered by presence DESC, then alphabetically."""
    sample = resources.list_for(tenant_id, kind=kind, limit=sample_size)
    if not sample:
        return ()

    counts: dict[str, int] = {}
    examples: dict[str, list[str]] = {}
    numeric_votes: dict[str, int] = {}

    for resource in sample:
        for field_name, value in resource.data.items():
            counts[field_name] = counts.get(field_name, 0) + 1
            bucket = examples.setdefault(field_name, [])
            if len(bucket) < _MAX_EXAMPLES_PER_FIELD:
                bucket.append(_short_value(value))
            if _is_numeric(value):
                numeric_votes[field_name] = numeric_votes.get(field_name, 0) + 1

    total = len(sample)
    fields = [
        FieldFrequency(
            name=name,
            presence=counts[name] / total,
            example_values=tuple(examples.get(name, [])),
            is_numeric=(numeric_votes.get(name, 0) / counts[name]) >= _NUMERIC_THRESHOLD,
        )
        for name in counts
    ]
    fields.sort(key=lambda f: (-f.presence, f.name))
    return tuple(fields)


def top_filter_keys(
    query_log: QueryLogPort,
    tenant_id: str,
    *,
    days: int = _DEFAULT_DAYS_WINDOW,
    limit: int = _DEFAULT_TOP_FILTERS,
) -> tuple[FilterFrequency, ...]:
    """Aggregate the most-used filter keys from recent query log entries.

    ``max_price`` / ``min_price`` roll up to ``price``, so the heatmap
    surfaces the underlying field instead of the operator twice."""
    cutoff = datetime.now(UTC) - timedelta(days=days)
    # 500 is generous for a single tenant; we'd cap higher only when we
    # start running this off a background job.
    entries = query_log.list_recent(tenant_id, limit=500)
    counter: dict[str, int] = {}
    for entry in entries:
        if entry.created_at < cutoff:
            continue
        for raw_key in entry.filters:
            actual = raw_key
            if raw_key.startswith("max_") or raw_key.startswith("min_"):
                actual = raw_key.split("_", 1)[1]
            counter[actual] = counter.get(actual, 0) + 1
    ordered = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))
    return tuple(FilterFrequency(key=k, count=c) for k, c in ordered[:limit])


def _is_numeric(value: Any) -> bool:  # noqa: ANN401 — arbitrary JSONB value
    """A value counts as numeric if it parses to a float (excluding bools).
    bool is a subclass of int in Python — we don't want True/False to bump
    a field's numeric vote."""
    if isinstance(value, bool):
        return False
    try:
        float(value)
    except (TypeError, ValueError):
        return False
    return True


def _short_value(value: Any) -> str:  # noqa: ANN401
    """Stringify + cap. Long descriptions get truncated so the hints block
    stays compact in the agent's prompt."""
    text = str(value).strip()
    if len(text) <= _EXAMPLE_MAX_CHARS:
        return text
    return text[: _EXAMPLE_MAX_CHARS - 1].rstrip() + "…"


class LearningService:
    """Wraps the two aggregations and the SOUL hints renderer in one
    object the agent loop can hold a reference to."""

    def __init__(
        self,
        *,
        resources: ResourceRepositoryPort,
        query_log: QueryLogPort,
    ) -> None:
        self._resources = resources
        self._query_log = query_log

    def insights(
        self,
        tenant_id: str,
        *,
        kind: str | None = None,
        sample_size: int = _DEFAULT_SAMPLE_SIZE,
        days: int = _DEFAULT_DAYS_WINDOW,
        top_n: int = _DEFAULT_TOP_FILTERS,
    ) -> LearningInsights:
        fields = discover_schema(
            self._resources,
            tenant_id,
            sample_size=sample_size,
            kind=kind,
        )
        top = top_filter_keys(
            self._query_log,
            tenant_id,
            days=days,
            limit=top_n,
        )
        return LearningInsights(
            tenant_id=tenant_id,
            sample_size=sample_size,
            window_days=days,
            fields=fields,
            top_filters=top,
            generated_at=datetime.now(UTC),
        )

    def render_soul_hints(
        self,
        tenant_id: str,
        *,
        kind: str | None = None,
    ) -> str:
        """Render a short Markdown block the SOUL prompt can include. Empty
        string when there's nothing useful to say — the agent loop drops
        the section entirely instead of injecting an "available fields:"
        header with nothing under it."""
        insights = self.insights(tenant_id, kind=kind)
        if not insights.fields:
            return ""

        # Only surface fields that appear in at least a quarter of the
        # sample — sparse fields are usually noise and waste tokens.
        useful = [f for f in insights.fields if f.presence >= _MIN_PRESENCE_FOR_HINT]
        if not useful:
            return ""

        lines: list[str] = ["## Catalog hints"]
        lines.append(
            "These are the fields present in the tenant's catalog. Use them "
            "when filtering or quoting:"
        )
        for field in useful[:10]:  # cap at 10 to keep the prompt bounded
            tag = "numeric" if field.is_numeric else "text"
            examples = ", ".join(field.example_values[:3])
            example_part = f" — e.g. {examples}" if examples else ""
            lines.append(f"- `{field.name}` ({tag}, {field.presence:.0%}){example_part}")

        if insights.top_filters:
            lines.append("")
            lines.append("Buyers most often filter on these fields — lean into them:")
            for filt in insights.top_filters:
                lines.append(f"- `{filt.key}` ({filt.count} recent queries)")

        return "\n".join(lines)
