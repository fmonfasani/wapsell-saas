"""Tests for the WhatsApp gateway: in-memory + Kapso adapter + webhook E2E."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any, cast

from fastapi.testclient import TestClient
import httpx
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from waseller import buyer_id_for
from waseller.whatsapp.gateway import (
    GatewayError,
    InMemoryGateway,
    KapsoGateway,
    OutboundMessage,
)

pytestmark = pytest.mark.unit


# --- InMemoryGateway --------------------------------------------------------


class TestInMemoryGateway:
    async def test_send_text_records_outbound(self) -> None:
        gw = InMemoryGateway()
        msg = await gw.send_text("549111", "hola", tenant_id="t1")
        assert msg.to_number == "549111"
        assert msg.body == "hola"
        assert msg.kind == "text"
        assert msg.tenant_id == "t1"
        assert msg.vendor_message_id is not None
        assert gw.sent == [msg]

    async def test_send_template_carries_params(self) -> None:
        gw = InMemoryGateway()
        msg = await gw.send_template("549111", "welcome", params={"name": "Acme"}, tenant_id="t1")
        assert msg.kind == "template"
        assert msg.template_id == "welcome"
        assert msg.template_params == {"name": "Acme"}
        assert "welcome" in msg.body

    async def test_sequential_sends_accumulate(self) -> None:
        gw = InMemoryGateway()
        await gw.send_text("a", "1")
        await gw.send_text("b", "2")
        assert [m.body for m in gw.sent] == ["1", "2"]


# --- KapsoGateway (mocked httpx client) ------------------------------------


class _FakeResponse:
    def __init__(self, status: int, body: dict[str, Any] | None = None) -> None:
        self.status_code = status
        self._body = body or {}
        self.text = json.dumps(self._body)

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeClient:
    def __init__(
        self, response: _FakeResponse | None = None, raises: Exception | None = None
    ) -> None:
        self._response = response or _FakeResponse(200, {"messages": [{"id": "wamid.ABC"}]})
        self._raises = raises
        self.posts: list[tuple[str, dict[str, Any]]] = []

    async def post(self, url: str, *, json: dict[str, Any], timeout: float) -> _FakeResponse:  # noqa: ASYNC109 — mirrors httpx signature
        self.posts.append((url, json))
        if self._raises is not None:
            raise self._raises
        return self._response


class TestKapsoGateway:
    async def test_send_text_posts_correct_payload(self) -> None:
        client = _FakeClient()
        gw = KapsoGateway(client, base_url="http://kapso:4000")
        msg = await gw.send_text("549111", "hola", tenant_id="t1")

        assert len(client.posts) == 1
        url, payload = client.posts[0]
        assert url == "http://kapso:4000/messages"
        assert payload == {
            "to": "549111",
            "type": "text",
            "text": {"body": "hola"},
            "tenant_id": "t1",
        }
        assert msg.vendor_message_id == "wamid.ABC"

    async def test_send_template_posts_correct_payload(self) -> None:
        client = _FakeClient()
        gw = KapsoGateway(client)
        msg = await gw.send_template("549111", "welcome", params={"name": "Acme"})

        _, payload = client.posts[0]
        assert payload["type"] == "template"
        assert payload["template"] == {"name": "welcome", "parameters": {"name": "Acme"}}
        assert msg.template_id == "welcome"
        assert msg.template_params == {"name": "Acme"}

    async def test_4xx_raises_gateway_error(self) -> None:
        client = _FakeClient(response=_FakeResponse(401, {"error": "bad token"}))
        gw = KapsoGateway(client)
        with pytest.raises(GatewayError, match="401"):
            await gw.send_text("x", "y")

    async def test_transport_failure_wrapped_as_gateway_error(self) -> None:
        client = _FakeClient(raises=httpx.ConnectError("connection refused"))
        gw = KapsoGateway(client)
        with pytest.raises(GatewayError, match="kapso request failed"):
            await gw.send_text("x", "y")

    async def test_strips_trailing_slash_from_base_url(self) -> None:
        client = _FakeClient()
        gw = KapsoGateway(client, base_url="http://kapso:4000/")
        await gw.send_text("x", "y")
        assert client.posts[0][0] == "http://kapso:4000/messages"


# --- Webhook → gateway E2E (the P03 smoke) ---------------------------------


def _meta_payload(phone_number_id: str, from_number: str, text: str) -> dict[str, object]:
    return {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "metadata": {"phone_number_id": phone_number_id},
                            "messages": [
                                {
                                    "type": "text",
                                    "from": from_number,
                                    "id": f"m-{text[:6]}",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _signed_post(client: TestClient, secret: str, body: dict[str, object]) -> httpx.Response:
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    # cast: TestClient.post is typed as Any in older starlette releases CI may pick up;
    # newer versions consider this redundant — ignore both to stay portable.
    return cast(  # type: ignore[redundant-cast]
        httpx.Response,
        client.post("/webhook", content=raw, headers={"X-Hub-Signature-256": sig}),
    )


class TestWebhookGatewayPipeline:
    """webhook → router → memory → agent-loop → gateway.send_text → memory(agent)."""

    def test_inbound_triggers_gateway_send_and_remembers_agent_reply(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("META_APP_SECRET", "shh")
        tenant = live_client.create_tenant("GwSmoke", "gw-smoke")
        live_client.tenants.repository.update(
            tenant.model_copy(update={"whatsapp_phone_number_id": "GW-PN"})
        )
        # Snapshot gateway state before the call so we can assert the delta.
        gw = live_client.gateway
        assert isinstance(gw, InMemoryGateway)
        before = len(gw.sent)

        with TestClient(app) as http:
            res = _signed_post(
                http, "shh", _meta_payload("GW-PN", "549333", "quiero comprar urgente")
            )

        assert res.status_code == 200
        # One outbound was sent.
        assert len(gw.sent) == before + 1
        outbound: OutboundMessage = gw.sent[-1]
        assert outbound.to_number == "549333"
        assert outbound.tenant_id == tenant.id
        # P12b: reply now comes from the agent loop. Default LLM is EchoLLM,
        # which echoes the buyer's text into the response — that's the cheapest
        # observable signal that the loop actually ran (vs the old hardcoded
        # placeholder with no buyer content).
        assert "quiero comprar urgente" in outbound.body

    async def test_memory_holds_both_buyer_and_agent_turns(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("META_APP_SECRET", "shh")
        tenant = live_client.create_tenant("GwSmoke2", "gw-smoke-2")
        live_client.tenants.repository.update(
            tenant.model_copy(update={"whatsapp_phone_number_id": "GW-PN-2"})
        )

        with TestClient(app) as http:
            _signed_post(http, "shh", _meta_payload("GW-PN-2", "549444", "hola"))

        history = await live_client.memory.recall(buyer_id_for("gw-smoke-2", "549444"))
        # Two interactions: buyer + agent reply
        assert [h.role for h in history] == ["buyer", "agent"]
        assert history[0].text == "hola"
        assert "Recibimos tu mensaje" in history[1].text
