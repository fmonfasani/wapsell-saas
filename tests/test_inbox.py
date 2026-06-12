"""Tests for the inbox bot-pause registry + send/pause/resume endpoints.

Covers:
- :class:`InMemoryBotPauseRepository` lifecycle (pause expires, resume removes,
  upsert overwrites).
- Webhook handler skips ``agent.respond`` when paused (and persists the
  inbound buyer turn anyway so the human still sees it).
- Auto-pause when the handoff detector escalates (8h default, configurable
  via tenant ``auto_pause_hours``).
- ``POST /conversations/{buyer_id}/send`` writes a human turn and pauses
  the bot in the same call.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from wapsell.inbox import InMemoryBotPauseRepository
from wapsell.models import HandoffConfig

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


class TestInMemoryBotPauseRepository:
    def test_is_paused_false_when_empty(self) -> None:
        repo = InMemoryBotPauseRepository()
        assert repo.is_paused("t1", "demo:1") is False

    def test_pause_then_is_paused_true(self) -> None:
        repo = InMemoryBotPauseRepository()
        until = datetime.now(UTC) + timedelta(hours=1)
        repo.pause("t1", "demo:1", until)
        assert repo.is_paused("t1", "demo:1") is True

    def test_expired_pause_is_not_paused(self) -> None:
        repo = InMemoryBotPauseRepository()
        # Pause ending in the past — should read as inactive.
        repo.pause("t1", "demo:1", datetime.now(UTC) - timedelta(seconds=1))
        assert repo.is_paused("t1", "demo:1") is False

    def test_resume_removes_pause(self) -> None:
        repo = InMemoryBotPauseRepository()
        repo.pause("t1", "demo:1", datetime.now(UTC) + timedelta(hours=1))
        repo.resume("t1", "demo:1")
        assert repo.is_paused("t1", "demo:1") is False
        assert repo.get("t1", "demo:1") is None

    def test_pause_upserts(self) -> None:
        # Re-pausing extends (or shortens) the window — last write wins.
        repo = InMemoryBotPauseRepository()
        first = datetime.now(UTC) + timedelta(hours=1)
        second = datetime.now(UTC) + timedelta(hours=24)
        repo.pause("t1", "demo:1", first)
        repo.pause("t1", "demo:1", second)
        got = repo.get("t1", "demo:1")
        assert got is not None
        assert got.paused_until == second

    def test_list_active_filters_expired(self) -> None:
        repo = InMemoryBotPauseRepository()
        now = datetime.now(UTC)
        repo.pause("t1", "demo:1", now + timedelta(hours=1))
        repo.pause("t1", "demo:2", now - timedelta(seconds=1))
        repo.pause("t2", "other:1", now + timedelta(hours=1))
        active = repo.list_active("t1")
        assert {p.buyer_id for p in active} == {"demo:1"}


class TestPauseEndpoints:
    def _make_tenant(self, http: TestClient, slug: str) -> tuple[str, str]:
        body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return body["id"], slug

    def test_pause_and_resume_roundtrip(self, http: TestClient) -> None:
        tid, slug = self._make_tenant(http, "pause-rt")
        bid = f"{slug}:5491100000001"
        res = http.post(f"/tenants/{tid}/conversations/{bid}/pause", json={"hours": 1})
        assert res.status_code == 200
        assert res.json()["bot_paused"] is True
        assert res.json()["bot_paused_until"] is not None

        res = http.post(f"/tenants/{tid}/conversations/{bid}/resume")
        assert res.status_code == 200
        assert res.json()["bot_paused"] is False
        assert res.json()["bot_paused_until"] is None

    def test_pause_zero_hours_rejected(self, http: TestClient) -> None:
        tid, slug = self._make_tenant(http, "pause-zero")
        bid = f"{slug}:5491100000002"
        res = http.post(f"/tenants/{tid}/conversations/{bid}/pause", json={"hours": 0})
        assert res.status_code == 422

    def test_cross_tenant_pause_rejected(self, http: TestClient) -> None:
        tid_a, _ = self._make_tenant(http, "pause-a")
        _, slug_b = self._make_tenant(http, "pause-b")
        # Trying to pause a buyer that belongs to tenant B from tenant A's
        # endpoint should 404 — buyer_id prefix mismatch.
        bid_b = f"{slug_b}:5491100000003"
        res = http.post(f"/tenants/{tid_a}/conversations/{bid_b}/pause", json={"hours": 1})
        assert res.status_code == 404


class TestSendHumanMessage:
    def _make_tenant(self, http: TestClient, slug: str) -> tuple[str, str]:
        body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return body["id"], slug

    def test_send_persists_human_turn_and_pauses_bot(self, http: TestClient) -> None:
        tid, slug = self._make_tenant(http, "send-pause")
        bid = f"{slug}:5491100000010"
        res = http.post(
            f"/tenants/{tid}/conversations/{bid}/send",
            json={"text": "hola desde el humano", "pause_hours": 4},
        )
        assert res.status_code == 201
        body = res.json()
        assert body["role"] == "agent"
        assert body["text"] == "hola desde el humano"
        assert body["metadata"]["human"] == "true"
        # Pause window stamped into the turn metadata so the dashboard can
        # render "muted until 14:00" without a second lookup.
        assert "bot_paused_until" in body["metadata"]

        # And the bot really is paused now.
        assert live_client.bot_pauses.is_paused(tid, bid) is True

    def test_send_with_zero_pause_does_not_pause(self, http: TestClient) -> None:
        # Power-user opt-out: send a one-off without muting the bot.
        tid, slug = self._make_tenant(http, "send-nopause")
        bid = f"{slug}:5491100000011"
        res = http.post(
            f"/tenants/{tid}/conversations/{bid}/send",
            json={"text": "ping", "pause_hours": 0},
        )
        assert res.status_code == 201
        assert live_client.bot_pauses.is_paused(tid, bid) is False

    def test_empty_text_rejected(self, http: TestClient) -> None:
        tid, slug = self._make_tenant(http, "send-empty")
        bid = f"{slug}:5491100000012"
        res = http.post(
            f"/tenants/{tid}/conversations/{bid}/send",
            json={"text": "   ", "pause_hours": 1},
        )
        assert res.status_code == 422

    def test_thread_detail_reflects_paused_state(self, http: TestClient) -> None:
        tid, slug = self._make_tenant(http, "send-detail")
        bid = f"{slug}:5491100000013"
        http.post(
            f"/tenants/{tid}/conversations/{bid}/send",
            json={"text": "humano respondiendo", "pause_hours": 2},
        )
        res = http.get(f"/tenants/{tid}/conversations/{bid}")
        assert res.status_code == 200
        body = res.json()
        assert body["bot_paused"] is True
        assert body["bot_paused_until"] is not None
        # The human turn is in the transcript.
        assert any(t["text"] == "humano respondiendo" for t in body["turns"])


class TestAutoPauseOnHandoff:
    """End-to-end check that handoff escalation auto-pauses the bot via
    the webhook handler's call to ``_client.bot_pauses.pause``. We don't go
    through Meta's full webhook payload here — we exercise the handler
    function directly with a forged InboundMessage."""

    async def test_handoff_triggers_auto_pause(self, http: TestClient) -> None:
        from services.api.main import _process_inbound_message  # noqa: PLC0415

        from wapsell.models import InboundMessage  # noqa: PLC0415

        created = http.post(
            "/tenants",
            json={"name": "Handoff Auto", "slug": "handoff-auto-pause"},
        ).json()
        tid = created["id"]
        # Configure handoff with auto-pause of 6h.
        http.put(
            f"/tenants/{tid}/handoff",
            json={
                "enabled": True,
                "keywords": ["humano"],
                "webhook_url": None,
                "handoff_message": "Te paso con un humano.",
                "auto_pause_hours": 6,
            },
        )

        tenant = live_client.tenants.get(tid)
        msg = InboundMessage(
            tenant_id=tid,
            from_number="5491100000099",
            text="quiero hablar con un humano por favor",
            message_id="wamid.test.handoff",
        )
        await _process_inbound_message(tenant, msg)

        bid = f"{tenant.slug}:5491100000099"
        assert live_client.bot_pauses.is_paused(tid, bid) is True

    async def test_handoff_with_zero_hours_does_not_pause(self, http: TestClient) -> None:
        # auto_pause_hours=0 means "warm handoff" — bot keeps replying.
        from services.api.main import _process_inbound_message  # noqa: PLC0415

        from wapsell.models import InboundMessage  # noqa: PLC0415

        created = http.post(
            "/tenants",
            json={"name": "Warm Handoff", "slug": "warm-handoff"},
        ).json()
        tid = created["id"]
        http.put(
            f"/tenants/{tid}/handoff",
            json={
                "enabled": True,
                "keywords": ["humano"],
                "webhook_url": None,
                "handoff_message": "Te paso (warm).",
                "auto_pause_hours": 0,
            },
        )
        # Sanity: confirm the cfg actually persisted with hours=0 (Pydantic
        # default is 8, so a bad copy would silently fall back).
        cfg = HandoffConfig.model_validate(http.get(f"/tenants/{tid}/handoff").json()["config"])
        assert cfg.auto_pause_hours == 0

        tenant = live_client.tenants.get(tid)
        msg = InboundMessage(
            tenant_id=tid,
            from_number="5491100000100",
            text="quiero hablar con un humano",
            message_id="wamid.test.warm",
        )
        await _process_inbound_message(tenant, msg)

        bid = f"{tenant.slug}:5491100000100"
        assert live_client.bot_pauses.is_paused(tid, bid) is False
