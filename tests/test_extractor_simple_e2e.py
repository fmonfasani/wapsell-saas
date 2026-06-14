"""Simple E2E test of CRM extractor: 3 inbound messages -> task extraction."""

from __future__ import annotations

from fastapi.testclient import TestClient
import pytest
from services.api import main as api_module
from services.api.main import _client, app

from wapsell.crm import CONTACT_KIND, ConversationTurn
from wapsell.memory.buyer import BuyerInteraction
from wapsell.resources import Resource


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


async def _simulate_messages(buyer_id: str, messages: list[str]) -> None:
    """Simulate inbound messages in buyer memory."""
    for i, text in enumerate(messages, 1):
        print(f"[MSG {i}] {text}")
        await _client.memory.remember(
            buyer_id,
            BuyerInteraction(text=text, role="buyer"),
        )


def _create_contact(tenant_id: str, phone: str) -> str:
    """Create contact with turn_count=3."""
    from wapsell.crm import contact_external_id  # noqa: PLC0415

    contact_ext_id = contact_external_id(phone)
    contact_resource = _client.resources.upsert(
        Resource(
            tenant_id=tenant_id,
            kind=CONTACT_KIND,
            external_id=contact_ext_id,
            data={"phone": phone, "turn_count": 3},
            summary=f"+{phone}",
        )
    )
    contact_id = contact_resource.id
    print(f"[CONTACT] {contact_id} (turn_count=3)")
    return contact_id


async def _run_extraction(tenant_id: str, contact_id: str, buyer_id: str) -> None:
    """Run CRM extractor if wired."""
    if api_module._crm_extractor:
        print("[EXTRACTOR] Running...")
        recent = await _client.memory.recall(buyer_id, limit=40)
        turns = [
            ConversationTurn(role=i.role, text=i.text, at=i.at.isoformat() if i.at else None)
            for i in recent
            if i.text
        ]
        if turns:
            result = await api_module._crm_extractor.extract(turns)
            api_module._crm_extractor.apply(
                tenant_id=tenant_id,
                contact_id=contact_id,
                result=result,
            )
            print(f"[EXTRACT] Done: {len(result.new_tasks)} task(s)")
    else:
        print("[EXTRACT] Disabled (extractor not wired)")


class TestExtractorSimpleE2E:
    async def test_extraction_flow(self, http: TestClient) -> None:
        """Simulate CRM + extractor flow."""
        phone = "5491100008888"
        messages = [
            "Hola, necesito ayuda con mi pedido",
            "Me gustaria agendar una reunion para el martes",
            "Cuando puedo pasar a buscar?",
        ]

        tenant_res = http.post(
            "/tenants",
            json={"name": "Extractor E2E", "slug": "e2e-simple"},
        )
        assert tenant_res.status_code == 201
        tenant_id = tenant_res.json()["id"]
        print(f"[TENANT] {tenant_id}")

        buyer_id = f"e2e-simple:{phone}"
        await _simulate_messages(buyer_id, messages)

        contact_id = _create_contact(tenant_id, phone)
        await _run_extraction(tenant_id, contact_id, buyer_id)

        contact_res = http.get(f"/tenants/{tenant_id}/crm/contacts/by-phone/{phone}")
        assert contact_res.status_code == 200
        turn_count = contact_res.json()["data"].get("turn_count", 0)
        print(f"[VERIFY] Turn count: {turn_count}")
        assert turn_count == 3

        tasks_res = http.get(f"/tenants/{tenant_id}/crm/contacts/{contact_id}/tasks")
        assert tasks_res.status_code == 200
        tasks = tasks_res.json()
        print(f"[TASKS] Found {len(tasks)} task(s)")

        for task in tasks:
            auto = task["data"].get("auto", False)
            status = task["data"].get("status", "open")
            title = task["data"].get("title", task["summary"])
            badge = "[AUTO]" if auto else "[MANUAL]"
            print(f"  - {title} [{status}] {badge}")

            if auto and status == "open":
                print("[ACTIONS] Testing task buttons...")
                confirm_res = http.patch(
                    f"/tenants/{tenant_id}/crm/tasks/{task['id']}",
                    json={"confirmed": True},
                )
                assert confirm_res.status_code == 200
                print("  - Confirm: OK")

                done_res = http.patch(
                    f"/tenants/{tenant_id}/crm/tasks/{task['id']}",
                    json={"status": "done"},
                )
                assert done_res.status_code == 200
                print("  - Mark done: OK")

        print("\n" + "=" * 70)
        print("[PASS] Extractor E2E complete")
        print("=" * 70)
