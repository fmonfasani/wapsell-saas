"""Tests for buyer memory: in-memory bounded buffer + Honcho adapter + webhook E2E."""

from __future__ import annotations

from datetime import UTC, datetime
import hashlib
import hmac
import json
from typing import Any

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from waseller import buyer_id_for
from waseller.memory.buyer import (
    BuyerInteraction,
    HonchoBuyerMemory,
    InMemoryBuyerMemory,
)

pytestmark = pytest.mark.unit


# --- InMemoryBuyerMemory ----------------------------------------------------


class TestInMemoryBuyerMemory:
    async def test_recall_empty_for_new_buyer(self) -> None:
        mem = InMemoryBuyerMemory()
        assert await mem.recall("nobody") == []

    async def test_remember_then_recall_chronological(self) -> None:
        mem = InMemoryBuyerMemory()
        for i in range(3):
            await mem.remember("alice", BuyerInteraction(text=f"msg-{i}"))
        assert [t.text for t in await mem.recall("alice")] == ["msg-0", "msg-1", "msg-2"]

    async def test_limit_returns_most_recent_only(self) -> None:
        mem = InMemoryBuyerMemory()
        for i in range(5):
            await mem.remember("alice", BuyerInteraction(text=f"msg-{i}"))
        assert [t.text for t in await mem.recall("alice", limit=2)] == ["msg-3", "msg-4"]

    async def test_limit_zero_or_negative_returns_empty(self) -> None:
        mem = InMemoryBuyerMemory()
        await mem.remember("alice", BuyerInteraction(text="x"))
        assert await mem.recall("alice", limit=0) == []
        assert await mem.recall("alice", limit=-1) == []

    async def test_max_items_caps_history_dropping_oldest(self) -> None:
        mem = InMemoryBuyerMemory(max_items=3)
        for i in range(5):
            await mem.remember("alice", BuyerInteraction(text=f"msg-{i}"))
        # Oldest two dropped; only the last three remain.
        assert [t.text for t in await mem.recall("alice")] == ["msg-2", "msg-3", "msg-4"]

    async def test_summary_empty_for_unknown_buyer(self) -> None:
        assert await InMemoryBuyerMemory().summary("nobody") == "no prior interactions"

    async def test_summary_includes_recent_turns_per_dialectic_depth(self) -> None:
        # depth=1 → up to 2 raw interactions (1 turn pair).
        mem = InMemoryBuyerMemory(dialectic_depth=1)
        await mem.remember("alice", BuyerInteraction(text="hola", role="buyer"))
        await mem.remember("alice", BuyerInteraction(text="hola!", role="agent"))
        await mem.remember("alice", BuyerInteraction(text="precio?", role="buyer"))
        await mem.remember("alice", BuyerInteraction(text="$10", role="agent"))

        s = await mem.summary("alice")
        # Only the last 2 (depth*2): precio? + $10
        assert "precio?" in s
        assert "$10" in s
        assert "hola" not in s

    async def test_separate_buyers_have_independent_history(self) -> None:
        mem = InMemoryBuyerMemory()
        await mem.remember("alice", BuyerInteraction(text="a-1"))
        await mem.remember("bob", BuyerInteraction(text="b-1"))
        assert [t.text for t in await mem.recall("alice")] == ["a-1"]
        assert [t.text for t in await mem.recall("bob")] == ["b-1"]


# --- buyer_id_for -----------------------------------------------------------


def test_buyer_id_composition() -> None:
    assert buyer_id_for("acme", "549111") == "acme:549111"


# --- HonchoBuyerMemory adapter (mocked client) ------------------------------


class _FakeHonchoClient:
    """Records calls; returns canned message payloads for list_messages."""

    def __init__(self, list_response: list[dict[str, Any]] | None = None) -> None:
        self.appended: list[dict[str, Any]] = []
        self.list_calls: list[dict[str, Any]] = []
        self.summary_calls: list[dict[str, Any]] = []
        self._list_response = list_response or []

    async def append_message(self, **kwargs: Any) -> None:
        self.appended.append(kwargs)

    async def list_messages(self, **kwargs: Any) -> list[dict[str, Any]]:
        self.list_calls.append(kwargs)
        return list(self._list_response)

    async def dialectic_summary(self, **kwargs: Any) -> str:
        self.summary_calls.append(kwargs)
        return "honcho-synthesized-summary"


class TestHonchoBuyerMemory:
    async def test_remember_forwards_to_client_with_namespace(self) -> None:
        client = _FakeHonchoClient()
        mem = HonchoBuyerMemory(client, namespace="tenant-x", dialectic_depth=3)
        await mem.remember("alice", BuyerInteraction(text="hi", metadata={"k": "v"}))

        assert len(client.appended) == 1
        call = client.appended[0]
        assert call["namespace"] == "tenant-x"
        assert call["user_id"] == "alice"
        assert call["content"] == "hi"
        assert call["role"] == "buyer"
        assert call["metadata"] == {"k": "v"}

    async def test_recall_maps_response_into_interactions(self) -> None:
        client = _FakeHonchoClient(
            list_response=[
                {
                    "content": "first",
                    "role": "buyer",
                    "at": datetime(2026, 1, 1, tzinfo=UTC).isoformat(),
                    "metadata": {"x": "1"},
                },
                {"content": "second", "role": "agent", "at": None, "metadata": None},
            ]
        )
        mem = HonchoBuyerMemory(client)
        results = await mem.recall("alice", limit=10)

        assert [r.text for r in results] == ["first", "second"]
        assert results[0].role == "buyer"
        assert results[0].metadata == {"x": "1"}
        assert results[1].metadata == {}
        assert client.list_calls[0]["limit"] == 10

    async def test_summary_uses_configured_depth(self) -> None:
        client = _FakeHonchoClient()
        mem = HonchoBuyerMemory(client, dialectic_depth=4)
        result = await mem.summary("alice")
        assert result == "honcho-synthesized-summary"
        assert client.summary_calls[0]["depth"] == 4


# --- Webhook end-to-end: 2 messages → memory accumulates --------------------


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
                                    "id": f"m-{text[:5]}",
                                    "text": {"body": text},
                                }
                            ],
                        }
                    }
                ]
            }
        ]
    }


def _signed_post(
    client: TestClient, secret: str, body: dict[str, object]
) -> Any:  # httpx.Response — Any avoids the import in tests
    raw = json.dumps(body).encode()
    sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    return client.post("/webhook", content=raw, headers={"X-Hub-Signature-256": sig})


class TestWebhookMemoryIntegration:
    async def test_two_messages_same_buyer_accumulate_in_memory(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("META_APP_SECRET", "shh")
        tenant = live_client.create_tenant("MemRouted", "mem-routed")
        live_client.tenants.repository.update(
            tenant.model_copy(update={"whatsapp_phone_number_id": "MEM-PN"})
        )

        with TestClient(app) as http:
            r1 = _signed_post(http, "shh", _meta_payload("MEM-PN", "549222", "hola"))
            r2 = _signed_post(http, "shh", _meta_payload("MEM-PN", "549222", "precio?"))
            assert r1.status_code == 200
            assert r2.status_code == 200

        bid = buyer_id_for("mem-routed", "549222")
        history = await live_client.memory.recall(bid)
        assert [h.text for h in history] == ["hola", "precio?"]
        # Tenant-scoped: a different tenant's same number is a different buyer_id.
        assert await live_client.memory.recall(buyer_id_for("other", "549222")) == []
