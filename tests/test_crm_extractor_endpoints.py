"""Tests for the CRM task endpoints (PR #52)."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from wapsell.models import InboundMessage

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


def _make_tenant(http: TestClient, slug: str) -> str:
    body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
    return str(body["id"])


async def _seed_contact(http: TestClient, slug: str, phone: str) -> tuple[str, str]:
    """Run a real inbound through the webhook so a contact resource exists.
    Returns (tenant_id, contact_id)."""
    from services.api.main import _process_inbound_message  # noqa: PLC0415

    tid = _make_tenant(http, slug)
    tenant = live_client.tenants.get(tid)
    msg = InboundMessage(
        tenant_id=tid,
        from_number=phone,
        text="hola",
        message_id=f"wamid.tasks.{tid}",
    )
    await _process_inbound_message(tenant, msg)
    contacts = http.get(f"/tenants/{tid}/crm/contacts").json()
    return tid, contacts[0]["id"]


def _seed_task(
    http: TestClient, tenant_id: str, contact_id: str, title: str, **extra: object
) -> str:
    """Insert a task resource via the generic resources endpoint so the
    tests don't depend on the LLM extractor being wired."""
    body = {
        "kind": "task",
        "data": {
            "contact_id": contact_id,
            "title": title,
            "status": "open",
            **extra,
        },
    }
    res = http.post(f"/tenants/{tenant_id}/resources", json=body)
    assert res.status_code == 201, res.text
    return str(res.json()["id"])


class TestListTasks:
    async def test_list_for_contact_filters_by_contact_id(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-list", "549110000201")
        _seed_task(http, tid, cid, "Mine", source="llm-extractor", auto=True)
        # Another contact to ensure scoping works.
        other_resp = http.post(
            f"/tenants/{tid}/resources",
            json={
                "kind": "contact",
                "external_id": "buyer:other",
                "data": {"phone": "other"},
            },
        )
        other_id = other_resp.json()["id"]
        _seed_task(http, tid, other_id, "Theirs")

        res = http.get(f"/tenants/{tid}/crm/contacts/{cid}/tasks")
        assert res.status_code == 200
        tasks = res.json()
        assert len(tasks) == 1
        assert tasks[0]["data"]["title"] == "Mine"

    async def test_list_for_tenant_with_status_filter(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-tenant", "549110000202")
        _seed_task(http, tid, cid, "Open one")
        closed_id = _seed_task(http, tid, cid, "Closed one")
        http.patch(
            f"/tenants/{tid}/crm/tasks/{closed_id}",
            json={"status": "done"},
        )
        res = http.get(f"/tenants/{tid}/crm/tasks?status=open")
        assert res.status_code == 200
        titles = [t["data"]["title"] for t in res.json()]
        assert titles == ["Open one"]


class TestPatchTask:
    async def test_mark_done(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-done", "549110000203")
        task_id = _seed_task(http, tid, cid, "Llamar")
        res = http.patch(f"/tenants/{tid}/crm/tasks/{task_id}", json={"status": "done"})
        assert res.status_code == 200
        assert res.json()["data"]["status"] == "done"

    async def test_confirm_marks_auto_as_reviewed(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-confirm", "549110000204")
        task_id = _seed_task(http, tid, cid, "Auto", auto=True, source="llm-extractor")
        res = http.patch(f"/tenants/{tid}/crm/tasks/{task_id}", json={"confirmed": True})
        assert res.status_code == 200
        assert res.json()["data"]["confirmed"] is True

    async def test_invalid_status_rejected(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-bad", "549110000205")
        task_id = _seed_task(http, tid, cid, "x")
        res = http.patch(f"/tenants/{tid}/crm/tasks/{task_id}", json={"status": "banana"})
        assert res.status_code == 400

    async def test_empty_due_at_clears(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-due", "549110000206")
        task_id = _seed_task(http, tid, cid, "Pendiente", due_at="2026-08-01T10:00:00+00:00")
        res = http.patch(f"/tenants/{tid}/crm/tasks/{task_id}", json={"due_at": ""})
        assert res.status_code == 200
        assert "due_at" not in res.json()["data"]


class TestDeleteTask:
    async def test_delete_removes_resource(self, http: TestClient) -> None:
        tid, cid = await _seed_contact(http, "tasks-del", "549110000207")
        task_id = _seed_task(http, tid, cid, "Borrar")
        res = http.delete(f"/tenants/{tid}/crm/tasks/{task_id}")
        assert res.status_code == 204
        # 404 on the second call.
        again = http.delete(f"/tenants/{tid}/crm/tasks/{task_id}")
        assert again.status_code == 404


class TestTenantIsolation:
    async def test_cross_tenant_task_returns_404(self, http: TestClient) -> None:
        tid1, cid1 = await _seed_contact(http, "tasks-iso-a", "549110000208")
        tid2 = _make_tenant(http, "tasks-iso-b")
        task_id = _seed_task(http, tid1, cid1, "Mine")
        assert (
            http.patch(f"/tenants/{tid2}/crm/tasks/{task_id}", json={"status": "done"}).status_code
            == 404
        )
        assert http.delete(f"/tenants/{tid2}/crm/tasks/{task_id}").status_code == 404
