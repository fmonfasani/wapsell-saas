"""Tests for buyer memory: in-memory bounded buffer + Honcho adapter + webhook E2E."""

from __future__ import annotations

from collections.abc import Sequence
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
    PostgresBuyerMemory,
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


# --- PostgresBuyerMemory (unit-level, mocked DB-API connection) -------------


class _FakeCursor:
    """Minimal PEP 249 cursor. Queues canned result sets so each .execute()
    can return different rows (recall vs trim vs insert)."""

    def __init__(self, results: Sequence[Sequence[tuple[object, ...]]]) -> None:
        self._results = list(results)
        self.executed: list[tuple[str, tuple[object, ...]]] = []
        self._last: list[tuple[object, ...]] = []

    def __enter__(self) -> _FakeCursor:
        return self

    def __exit__(self, *_: object) -> None: ...

    def execute(self, sql: str, params: tuple[object, ...] = ()) -> None:
        self.executed.append((sql, params))
        self._last = list(self._results.pop(0)) if self._results else []

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self._last)


class _FakeConn:
    def __init__(self, results: Sequence[Sequence[tuple[object, ...]]] = ()) -> None:
        self.cursors: list[_FakeCursor] = []
        self._results = list(results)
        self.commits = 0

    def cursor(self) -> _FakeCursor:
        cur = _FakeCursor(self._results)
        self.cursors.append(cur)
        return cur

    def commit(self) -> None:
        self.commits += 1


class TestPostgresBuyerMemory:
    async def test_remember_inserts_then_trims_and_commits(self) -> None:
        conn = _FakeConn()
        mem = PostgresBuyerMemory(conn, max_items=10)

        await mem.remember("alice", BuyerInteraction(text="hola", metadata={"k": "v"}))

        assert conn.commits == 1
        execs = conn.cursors[0].executed
        # Two queries: INSERT then DELETE (trim).
        assert execs[0][0].startswith("INSERT INTO buyer_interactions")
        assert execs[0][1][0] == "alice"
        assert execs[0][1][1] == "buyer"
        assert execs[0][1][2] == "hola"
        assert execs[1][0].startswith("DELETE FROM buyer_interactions")
        # Trim params: (buyer_id, max_items)
        assert execs[1][1] == ("alice", 10)

    async def test_recall_no_limit_uses_full_select_in_chronological_order(self) -> None:
        when = datetime(2026, 1, 1, 10, 0, tzinfo=UTC)
        rows = [("hola", "buyer", when, {"k": "v"})]
        conn = _FakeConn(results=[rows])

        result = await PostgresBuyerMemory(conn).recall("alice")

        sql, params = conn.cursors[0].executed[0]
        assert "ORDER BY at, id" in sql
        assert "LIMIT" not in sql
        assert params == ("alice",)
        assert len(result) == 1
        assert result[0].text == "hola"
        assert result[0].metadata == {"k": "v"}

    async def test_recall_with_limit_uses_subselect_reordered_ascending(self) -> None:
        # Mirror the InMemoryBuyerMemory contract: recall(limit=N) returns the
        # MOST RECENT N rows in chronological (oldest-first) order.
        rows: list[tuple[object, ...]] = [
            ("msg-3", "buyer", datetime(2026, 1, 1, 10, 3, tzinfo=UTC), {}),
            ("msg-4", "agent", datetime(2026, 1, 1, 10, 4, tzinfo=UTC), {}),
        ]
        conn = _FakeConn(results=[rows])

        result = await PostgresBuyerMemory(conn).recall("alice", limit=2)

        sql, params = conn.cursors[0].executed[0]
        # Subselect descending, outer ascending — the regression guard against
        # accidentally returning reverse-chrono history.
        assert "ORDER BY at DESC, id DESC LIMIT" in sql
        assert sql.rstrip().endswith("ORDER BY at, id")
        assert params == ("alice", 2)
        assert [r.text for r in result] == ["msg-3", "msg-4"]

    async def test_recall_zero_or_negative_short_circuits_without_db(self) -> None:
        conn = _FakeConn()
        mem = PostgresBuyerMemory(conn)
        assert await mem.recall("alice", limit=0) == []
        assert await mem.recall("alice", limit=-5) == []
        assert conn.cursors == []  # no DB hit

    async def test_row_to_interaction_decodes_json_string_metadata(self) -> None:
        # psycopg2 returns metadata as a JSON string; the adapter must decode.
        when = datetime(2026, 1, 1, tzinfo=UTC)
        rows = [("hola", "buyer", when.isoformat(), '{"x": "1"}')]
        conn = _FakeConn(results=[rows])
        result = await PostgresBuyerMemory(conn).recall("alice")
        assert result[0].metadata == {"x": "1"}
        assert result[0].at == when

    async def test_summary_uses_dialectic_depth_times_two(self) -> None:
        rows: list[tuple[object, ...]] = [
            ("hola", "buyer", datetime(2026, 1, 1, 10, 0, tzinfo=UTC), {}),
            ("hi", "agent", datetime(2026, 1, 1, 10, 1, tzinfo=UTC), {}),
            ("precio?", "buyer", datetime(2026, 1, 1, 10, 2, tzinfo=UTC), {}),
            ("$10", "agent", datetime(2026, 1, 1, 10, 3, tzinfo=UTC), {}),
        ]
        conn = _FakeConn(results=[rows])
        mem = PostgresBuyerMemory(conn, dialectic_depth=2)

        await mem.summary("alice")

        # depth=2 => limit = 4 (2 turn-pairs => 4 raw interactions).
        _sql, params = conn.cursors[0].executed[0]
        assert params == ("alice", 4)

    async def test_summary_empty_history_returns_canned_string(self) -> None:
        conn = _FakeConn(results=[[]])
        assert await PostgresBuyerMemory(conn).summary("nobody") == "no prior interactions"


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
        # After P03 the webhook also stores the auto-reply, so each inbound
        # produces a buyer+agent pair. Two messages → 4 interactions.
        assert [h.role for h in history] == ["buyer", "agent", "buyer", "agent"]
        assert [h.text for h in history if h.role == "buyer"] == ["hola", "precio?"]
        # Tenant-scoped: a different tenant's same number is a different buyer_id.
        assert await live_client.memory.recall(buyer_id_for("other", "549222")) == []
