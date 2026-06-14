"""Analytics and metrics collection for Wapsell SDK.

Tracks:
- Message volume per tenant
- Agent performance (latency, errors)
- LLM usage (tokens, models)
- Cache hit rates
- Skill invocation counts

Provides aggregated insights and per-tenant dashboards.
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from statistics import mean, median, quantiles
from typing import Any, Optional


class EventType(Enum):
    """Analytics event types."""

    MESSAGE_RECEIVED = "message_received"
    AGENT_RESPOND = "agent_respond"
    CACHE_HIT = "cache_hit"
    CACHE_MISS = "cache_miss"
    LLM_CALL = "llm_call"
    SKILL_INVOKED = "skill_invoked"
    ERROR = "error"
    HANDOFF = "handoff"


@dataclass
class AnalyticsEvent:
    """Single analytics event.

    Example:
        >>> event = AnalyticsEvent(
        ...     type=EventType.AGENT_RESPOND,
        ...     tenant_id="acme",
        ...     buyer_id="acme:+123",
        ...     latency_ms=250,
        ...     llm_model="openai/gpt-4o",
        ...     llm_tokens_input=128,
        ...     llm_tokens_output=45,
        ... )
    """

    type: EventType
    tenant_id: str
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Request context
    buyer_id: Optional[str] = None
    message_text: Optional[str] = None

    # Performance
    latency_ms: float = 0.0

    # LLM
    llm_model: Optional[str] = None
    llm_tokens_input: int = 0
    llm_tokens_output: int = 0

    # Cache
    cache_key: Optional[str] = None
    cache_ttl_used: Optional[int] = None

    # Skill
    skill_name: Optional[str] = None
    skill_confidence: Optional[float] = None

    # Error
    error_message: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        """Convert to JSON-serializable dict."""
        data = asdict(self)
        data["type"] = self.type.value
        data["timestamp"] = self.timestamp.isoformat()
        return data


@dataclass
class TenantMetrics:
    """Aggregated metrics for a single tenant."""

    tenant_id: str
    message_count: int = 0
    agent_calls: int = 0
    successful_calls: int = 0
    failed_calls: int = 0
    handoffs: int = 0

    # Performance (ms)
    latencies: list[float] = field(default_factory=list)

    # LLM usage
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    models_used: set[str] = field(default_factory=set)

    # Cache
    cache_hits: int = 0
    cache_misses: int = 0

    # Skills
    skills_invoked: dict[str, int] = field(default_factory=dict)

    def cache_hit_rate(self) -> float:
        """Cache hit rate (0.0-1.0)."""
        total = self.cache_hits + self.cache_misses
        return self.cache_hits / total if total > 0 else 0.0

    def avg_latency_ms(self) -> float:
        """Average agent response latency."""
        return mean(self.latencies) if self.latencies else 0.0

    def p95_latency_ms(self) -> float:
        """95th percentile latency."""
        if len(self.latencies) < 20:
            return max(self.latencies) if self.latencies else 0.0
        return quantiles(self.latencies, n=20)[18]  # 19th of 20 = 95%

    def total_tokens(self) -> int:
        """Total input + output tokens."""
        return self.total_input_tokens + self.total_output_tokens

    def avg_tokens_per_call(self) -> float:
        """Average tokens per agent call."""
        return self.total_tokens() / self.agent_calls if self.agent_calls > 0 else 0.0

    def estimated_cost_usd(self, input_rate: float = 0.005, output_rate: float = 0.015) -> float:
        """Rough USD cost estimate for LLM tokens.

        Args:
            input_rate: Cost per 1M input tokens (default: GPT-4o rates)
            output_rate: Cost per 1M output tokens

        Returns:
            Estimated cost in USD
        """
        return (self.total_input_tokens / 1_000_000 * input_rate
                + self.total_output_tokens / 1_000_000 * output_rate)

    def summary(self) -> dict[str, Any]:
        """Summary dict for dashboards."""
        return {
            "tenant_id": self.tenant_id,
            "message_count": self.message_count,
            "agent_calls": self.agent_calls,
            "success_rate": self.successful_calls / self.agent_calls if self.agent_calls > 0 else 0.0,
            "handoff_rate": self.handoffs / self.agent_calls if self.agent_calls > 0 else 0.0,
            "avg_latency_ms": round(self.avg_latency_ms(), 1),
            "p95_latency_ms": round(self.p95_latency_ms(), 1),
            "cache_hit_rate": round(self.cache_hit_rate() * 100, 1),
            "total_tokens": self.total_tokens(),
            "avg_tokens_per_call": round(self.avg_tokens_per_call(), 0),
            "estimated_cost_usd": round(self.estimated_cost_usd(), 4),
            "models_used": list(self.models_used),
            "top_skills": sorted(
                self.skills_invoked.items(), key=lambda x: x[1], reverse=True
            )[:5],
        }


class AnalyticsCollector:
    """Collects and aggregates analytics events.

    Thread-safe event collection with per-tenant aggregation.

    Example:
        >>> collector = AnalyticsCollector()
        >>> collector.record(
        ...     AnalyticsEvent(
        ...         type=EventType.AGENT_RESPOND,
        ...         tenant_id="acme",
        ...         latency_ms=245,
        ...     )
        ... )
        >>> metrics = collector.get_tenant_metrics("acme")
        >>> print(metrics.summary())
    """

    def __init__(self, max_events: int = 100_000) -> None:
        """Initialize collector.

        Args:
            max_events: Max events to keep in memory (FIFO eviction)
        """
        self.max_events = max_events
        self.events: list[AnalyticsEvent] = []
        self.metrics: dict[str, TenantMetrics] = defaultdict(
            lambda: TenantMetrics(tenant_id="")
        )

    def record(self, event: AnalyticsEvent) -> None:
        """Record an analytics event."""
        self.events.append(event)

        # Evict oldest if over capacity
        if len(self.events) > self.max_events:
            self.events.pop(0)

        # Update metrics
        tenant_id = event.tenant_id
        if tenant_id not in self.metrics:
            self.metrics[tenant_id] = TenantMetrics(tenant_id=tenant_id)

        metrics = self.metrics[tenant_id]

        match event.type:
            case EventType.MESSAGE_RECEIVED:
                metrics.message_count += 1

            case EventType.AGENT_RESPOND:
                metrics.agent_calls += 1
                metrics.successful_calls += 1
                if event.latency_ms > 0:
                    metrics.latencies.append(event.latency_ms)
                if event.llm_model:
                    metrics.models_used.add(event.llm_model)
                metrics.total_input_tokens += event.llm_tokens_input
                metrics.total_output_tokens += event.llm_tokens_output

            case EventType.CACHE_HIT:
                metrics.cache_hits += 1

            case EventType.CACHE_MISS:
                metrics.cache_misses += 1

            case EventType.SKILL_INVOKED:
                if event.skill_name:
                    metrics.skills_invoked[event.skill_name] = (
                        metrics.skills_invoked.get(event.skill_name, 0) + 1
                    )

            case EventType.HANDOFF:
                metrics.handoffs += 1

            case EventType.ERROR:
                metrics.failed_calls += 1

    def get_tenant_metrics(self, tenant_id: str) -> TenantMetrics:
        """Get aggregated metrics for a tenant."""
        return self.metrics.get(tenant_id, TenantMetrics(tenant_id=tenant_id))

    def get_all_metrics(self) -> dict[str, TenantMetrics]:
        """Get all tenant metrics."""
        return dict(self.metrics)

    def clear(self) -> None:
        """Clear all events and metrics."""
        self.events.clear()
        self.metrics.clear()

    def export_json(self, tenant_id: Optional[str] = None) -> str:
        """Export events as JSON.

        Args:
            tenant_id: If specified, export only events for this tenant

        Returns:
            JSON string
        """
        events = self.events
        if tenant_id:
            events = [e for e in events if e.tenant_id == tenant_id]

        return json.dumps([e.to_dict() for e in events], indent=2)


class AnalyticsReporter:
    """Generate dashboards and reports from analytics.

    Example:
        >>> reporter = AnalyticsReporter(collector)
        >>> print(reporter.global_summary())
        >>> print(reporter.tenant_dashboard("acme"))
    """

    def __init__(self, collector: AnalyticsCollector) -> None:
        """Initialize reporter.

        Args:
            collector: AnalyticsCollector instance
        """
        self.collector = collector

    def global_summary(self) -> str:
        """Global metrics across all tenants."""
        metrics = self.collector.get_all_metrics()
        if not metrics:
            return "No metrics collected yet."

        total_messages = sum(m.message_count for m in metrics.values())
        total_calls = sum(m.agent_calls for m in metrics.values())
        total_success = sum(m.successful_calls for m in metrics.values())
        total_tokens = sum(m.total_tokens() for m in metrics.values())
        total_cost = sum(m.estimated_cost_usd() for m in metrics.values())

        all_latencies = []
        for m in metrics.values():
            all_latencies.extend(m.latencies)

        lines = [
            "\n" + "=" * 70,
            "GLOBAL ANALYTICS SUMMARY",
            "=" * 70,
            f"Tenants: {len(metrics)}",
            f"Total messages: {total_messages:,}",
            f"Total agent calls: {total_calls:,}",
            f"Success rate: {100 * total_success / total_calls if total_calls > 0 else 0:.1f}%",
            f"Total tokens: {total_tokens:,}",
            f"Estimated cost: ${total_cost:.2f}",
            "",
            f"Global p50 latency: {median(all_latencies) if all_latencies else 0:.0f}ms",
            f"Global p95 latency: {quantiles(all_latencies, n=20)[18] if len(all_latencies) >= 20 else 0:.0f}ms",
            "=" * 70 + "\n",
        ]
        return "\n".join(lines)

    def tenant_dashboard(self, tenant_id: str) -> str:
        """Dashboard for a single tenant."""
        metrics = self.collector.get_tenant_metrics(tenant_id)
        summary = metrics.summary()

        lines = [
            "\n" + "=" * 70,
            f"TENANT DASHBOARD — {tenant_id}",
            "=" * 70,
            f"Messages: {summary['message_count']:,}",
            f"Agent calls: {summary['agent_calls']:,}",
            f"Success rate: {summary['success_rate'] * 100:.1f}%",
            f"Handoff rate: {summary['handoff_rate'] * 100:.1f}%",
            "",
            f"Avg latency: {summary['avg_latency_ms']:.1f}ms",
            f"P95 latency: {summary['p95_latency_ms']:.1f}ms",
            f"Cache hit rate: {summary['cache_hit_rate']:.1f}%",
            "",
            f"Total tokens: {summary['total_tokens']:,}",
            f"Avg tokens/call: {summary['avg_tokens_per_call']:.0f}",
            f"Estimated cost: ${summary['estimated_cost_usd']:.4f}",
            "",
            f"Models used: {', '.join(summary['models_used'])}",
        ]

        if summary["top_skills"]:
            lines.append("Top skills:")
            for skill, count in summary["top_skills"]:
                lines.append(f"  {skill}: {count} invocations")

        lines.append("=" * 70 + "\n")
        return "\n".join(lines)
