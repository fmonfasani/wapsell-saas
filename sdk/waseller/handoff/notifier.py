"""Handoff notifier — fires the per-tenant webhook when an escalation happens.

The agent loop calls this *after* the decision is final (the buyer already
got the "te paso con un humano" reply). Failures here MUST NOT block the
buyer-facing response, so callers wrap calls in try/except and log warnings.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol, runtime_checkable

import httpx

from waseller.handoff.detector import HandoffDecision
from waseller.models import Tenant

_log = logging.getLogger("waseller.handoff")

# HTTP status code threshold for "the receiver was unhappy with our payload" —
# anything 4xx/5xx is logged so an operator can spot a misconfigured webhook
# (wrong URL, auth missing, payload schema mismatch) without enabling debug.
_HTTP_ERROR_THRESHOLD = 400


@runtime_checkable
class HandoffNotifierPort(Protocol):
    """Send-on-escalation port. Implementations decide where to forward —
    HTTP webhook today; Slack / Discord / email adapters can layer on later
    without changing the call site."""

    async def notify(
        self,
        *,
        tenant: Tenant,
        buyer_id: str,
        message: str,
        decision: HandoffDecision,
    ) -> None: ...


class NullHandoffNotifier:
    """Default adapter — does nothing. Used in tests and when no tenant in
    the deployment has a webhook configured (so the SDK still composes)."""

    async def notify(
        self,
        *,
        tenant: Tenant,
        buyer_id: str,
        message: str,
        decision: HandoffDecision,
    ) -> None:
        return None


class HttpHandoffNotifier:
    """POSTs a small JSON payload to the per-tenant ``webhook_url``.

    Receivers (Slack incoming webhooks, Discord, n8n, Zapier, custom CRM
    inboxes) all accept a generic JSON POST so we don't shape per-vendor.
    Timeout is short on purpose — we don't want a slow webhook to slow down
    the agent reply path. Failures are logged and swallowed."""

    def __init__(self, client: httpx.AsyncClient, *, timeout: float = 5.0) -> None:
        self._client = client
        self._timeout = timeout

    async def notify(
        self,
        *,
        tenant: Tenant,
        buyer_id: str,
        message: str,
        decision: HandoffDecision,
    ) -> None:
        config = tenant.handoff_config
        if config is None or not config.webhook_url:
            return
        payload: dict[str, Any] = {
            "event": "handoff.escalated",
            "tenant": {"id": tenant.id, "slug": tenant.slug, "name": tenant.name},
            "buyer_id": buyer_id,
            "message": message,
            "matched_keyword": decision.matched_keyword,
        }
        try:
            response = await self._client.post(
                config.webhook_url, json=payload, timeout=self._timeout
            )
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                _log.warning(
                    "handoff webhook %s returned %d for tenant=%s",
                    config.webhook_url,
                    response.status_code,
                    tenant.slug,
                )
        except httpx.HTTPError as exc:
            # Network blip, DNS failure, timeout — never block the agent.
            _log.warning(
                "handoff webhook %s failed for tenant=%s: %s",
                config.webhook_url,
                tenant.slug,
                str(exc)[:200],
            )
