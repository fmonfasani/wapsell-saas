"""WhatsApp gateway port + in-memory + Kapso HTTP adapters.

The runtime never talks to Meta directly. It asks a :class:`WhatsAppGatewayPort`
to send a message; concrete adapters translate to the real wire protocol (Kapso
OSS gateway via HTTP). Tests use :class:`InMemoryGateway` to verify the runtime
side without any network calls.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Literal, Protocol, runtime_checkable
import uuid

MessageKind = Literal["text", "template"]

# HTTP status threshold for treating a response as a failure.
_HTTP_ERROR_FLOOR = 400


@dataclass(frozen=True, slots=True)
class OutboundMessage:
    """One outbound WhatsApp delivery (text or template)."""

    to_number: str
    body: str
    kind: MessageKind = "text"
    tenant_id: str | None = None
    template_id: str | None = None
    template_params: dict[str, str] = field(default_factory=dict)
    sent_at: datetime = field(default_factory=lambda: datetime.now(UTC))
    vendor_message_id: str | None = None
    metadata: dict[str, str] = field(default_factory=dict)


class GatewayError(RuntimeError):
    """Raised when the gateway can't deliver. Webhook handlers should swallow
    this and respond 200 to Meta (retries are Meta's job, not ours)."""

    code = "wapsell.gateway.error"


@runtime_checkable
class WhatsAppGatewayPort(Protocol):
    """Outbound boundary. Inbound flows through the webhook (parse_messages)."""

    async def send_text(
        self, to_number: str, text: str, *, tenant_id: str | None = None
    ) -> OutboundMessage: ...

    async def send_template(
        self,
        to_number: str,
        template_id: str,
        *,
        params: dict[str, str] | None = None,
        tenant_id: str | None = None,
    ) -> OutboundMessage: ...


@dataclass(slots=True)
class InMemoryGateway:
    """Records every outbound. Useful for tests + local smoke runs without Kapso."""

    sent: list[OutboundMessage] = field(default_factory=list)

    async def send_text(
        self, to_number: str, text: str, *, tenant_id: str | None = None
    ) -> OutboundMessage:
        msg = OutboundMessage(
            to_number=to_number,
            body=text,
            kind="text",
            tenant_id=tenant_id,
            vendor_message_id=f"mem-{uuid.uuid4().hex[:12]}",
        )
        self.sent.append(msg)
        return msg

    async def send_template(
        self,
        to_number: str,
        template_id: str,
        *,
        params: dict[str, str] | None = None,
        tenant_id: str | None = None,
    ) -> OutboundMessage:
        msg = OutboundMessage(
            to_number=to_number,
            body=f"[template:{template_id}]",
            kind="template",
            tenant_id=tenant_id,
            template_id=template_id,
            template_params=dict(params or {}),
            vendor_message_id=f"mem-{uuid.uuid4().hex[:12]}",
        )
        self.sent.append(msg)
        return msg


class KapsoGateway:
    """Kapso OSS HTTP gateway adapter.

    ``client`` is an httpx.AsyncClient-compatible object (duck-typed for tests).
    Endpoint shape mirrors Kapso's whatsapp-cloud-api facade: POST /messages with
    either a ``text`` or ``template`` payload. Reconcile exact field names against
    the live Kapso build at integration time — only this adapter changes.
    """

    def __init__(
        self,
        client: Any,  # noqa: ANN401 — httpx-compatible client is duck-typed
        *,
        base_url: str = "http://localhost:4000",
        timeout: float = 30.0,
    ) -> None:
        self._client = client
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def send_text(
        self, to_number: str, text: str, *, tenant_id: str | None = None
    ) -> OutboundMessage:
        payload = {"to": to_number, "type": "text", "text": {"body": text}}
        if tenant_id:
            payload["tenant_id"] = tenant_id
        return self._build_outbound(
            await self._post("/messages", payload),
            to_number=to_number,
            body=text,
            kind="text",
            tenant_id=tenant_id,
        )

    async def send_template(
        self,
        to_number: str,
        template_id: str,
        *,
        params: dict[str, str] | None = None,
        tenant_id: str | None = None,
    ) -> OutboundMessage:
        payload = {
            "to": to_number,
            "type": "template",
            "template": {"name": template_id, "parameters": dict(params or {})},
        }
        if tenant_id:
            payload["tenant_id"] = tenant_id
        response = await self._post("/messages", payload)
        msg = self._build_outbound(
            response,
            to_number=to_number,
            body=f"[template:{template_id}]",
            kind="template",
            tenant_id=tenant_id,
        )
        return OutboundMessage(
            to_number=msg.to_number,
            body=msg.body,
            kind=msg.kind,
            tenant_id=msg.tenant_id,
            template_id=template_id,
            template_params=dict(params or {}),
            sent_at=msg.sent_at,
            vendor_message_id=msg.vendor_message_id,
            metadata=msg.metadata,
        )

    async def _post(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            response = await self._client.post(url, json=payload, timeout=self._timeout)
        except Exception as exc:
            raise GatewayError(f"kapso request failed: {exc}") from exc
        status = getattr(response, "status_code", 0)
        if status >= _HTTP_ERROR_FLOOR:
            raise GatewayError(f"kapso returned {status}: {getattr(response, 'text', '')[:200]}")
        body = response.json()
        return body if isinstance(body, dict) else {"raw": body}

    @staticmethod
    def _build_outbound(
        response: dict[str, Any],
        *,
        to_number: str,
        body: str,
        kind: MessageKind,
        tenant_id: str | None,
    ) -> OutboundMessage:
        # Kapso returns {"messages":[{"id":"wamid..."}]} in the cloud-api facade.
        vendor_id = None
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            first = messages[0]
            if isinstance(first, dict):
                vendor_id = str(first.get("id")) if first.get("id") else None
        return OutboundMessage(
            to_number=to_number,
            body=body,
            kind=kind,
            tenant_id=tenant_id,
            vendor_message_id=vendor_id,
        )


class WhatsAppCloudGateway:
    """Meta WhatsApp Cloud API adapter — direct, no Kapso in between.

    Talks to ``POST https://graph.facebook.com/{version}/{phone_number_id}/messages``
    with ``Authorization: Bearer <access_token>``. Lighter than KapsoGateway when
    you don't need an OSS gateway in front (e.g. when running in a single-tenant
    deploy with one Meta number).

    ``client`` is an ``httpx.AsyncClient``-compatible object (duck-typed for tests).
    """

    BASE_URL = "https://graph.facebook.com"
    DEFAULT_LANG = "es"

    def __init__(
        self,
        client: Any,  # noqa: ANN401 — httpx-compatible client is duck-typed
        *,
        access_token: str,
        phone_number_id: str,
        graph_version: str = "v20.0",
        timeout: float = 30.0,
        default_language: str = DEFAULT_LANG,
    ) -> None:
        if not access_token:
            raise GatewayError("WhatsAppCloudGateway requires a non-empty access_token")
        if not phone_number_id:
            raise GatewayError("WhatsAppCloudGateway requires a non-empty phone_number_id")
        self._client = client
        self._access_token = access_token
        self._phone_number_id = phone_number_id
        self._timeout = timeout
        self._default_language = default_language
        self._endpoint = f"{self.BASE_URL}/{graph_version}/{phone_number_id}/messages"

    async def send_text(
        self, to_number: str, text: str, *, tenant_id: str | None = None
    ) -> OutboundMessage:
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to_number,
            "type": "text",
            "text": {"preview_url": False, "body": text},
        }
        return self._build_outbound(
            await self._post(payload),
            to_number=to_number,
            body=text,
            kind="text",
            tenant_id=tenant_id,
        )

    async def send_template(
        self,
        to_number: str,
        template_id: str,
        *,
        params: dict[str, str] | None = None,
        tenant_id: str | None = None,
    ) -> OutboundMessage:
        # Body-only template: maps `params` to the template's body placeholders.
        # Templates with headers/buttons/media need a richer build — extend here.
        components: list[dict[str, Any]] = []
        if params:
            components.append(
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": v} for v in params.values()],
                }
            )
        payload: dict[str, Any] = {
            "messaging_product": "whatsapp",
            "to": to_number,
            "type": "template",
            "template": {
                "name": template_id,
                "language": {"code": self._default_language},
                "components": components,
            },
        }
        response = await self._post(payload)
        msg = self._build_outbound(
            response,
            to_number=to_number,
            body=f"[template:{template_id}]",
            kind="template",
            tenant_id=tenant_id,
        )
        return OutboundMessage(
            to_number=msg.to_number,
            body=msg.body,
            kind=msg.kind,
            tenant_id=msg.tenant_id,
            template_id=template_id,
            template_params=dict(params or {}),
            sent_at=msg.sent_at,
            vendor_message_id=msg.vendor_message_id,
            metadata=msg.metadata,
        )

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._access_token}",
            "Content-Type": "application/json",
        }
        try:
            response = await self._client.post(
                self._endpoint, json=payload, headers=headers, timeout=self._timeout
            )
        except GatewayError:
            raise
        except Exception as exc:
            raise GatewayError(f"meta cloud api request failed: {exc}") from exc
        status = getattr(response, "status_code", 0)
        if status >= _HTTP_ERROR_FLOOR:
            raise GatewayError(
                f"meta cloud api returned {status}: {getattr(response, 'text', '')[:300]}"
            )
        body = response.json()
        return body if isinstance(body, dict) else {"raw": body}

    @staticmethod
    def _build_outbound(
        response: dict[str, Any],
        *,
        to_number: str,
        body: str,
        kind: MessageKind,
        tenant_id: str | None,
    ) -> OutboundMessage:
        # Meta returns {"messages":[{"id":"wamid..."}], "contacts":[...]}
        vendor_id = None
        messages = response.get("messages")
        if isinstance(messages, list) and messages:
            first = messages[0]
            if isinstance(first, dict) and first.get("id"):
                vendor_id = str(first["id"])
        return OutboundMessage(
            to_number=to_number,
            body=body,
            kind=kind,
            tenant_id=tenant_id,
            vendor_message_id=vendor_id,
        )
