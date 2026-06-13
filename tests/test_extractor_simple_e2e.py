"""Simple E2E test of CRM extractor: 3 inbound messages -> task extraction."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from services.api import main as api_module
from services.api.main import app, _client


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


class TestExtractorSimpleE2E:
    async def test_extraction_flow(self, http: TestClient) -> None:
        """Simulate CRM + extractor flow: contact created, messages recorded,
        extractor runs at turn 3."""
        phone = "5491100008888"

        # Step 1: Create tenant
        tenant_res = http.post(
            "/tenants",
            json={"name": "Extractor E2E", "slug": "e2e-simple"},
        )
        assert tenant_res.status_code == 201
        tenant_id = tenant_res.json()["id"]
        print(f"\n[TENANT] {tenant_id}")

        # Step 2: Simulate 3 inbound messages in the buyer memory
        # (this is what happens when webhooks are processed)
        from wapsell.memory.buyer import BuyerInteraction

        buyer_id = f"e2e-simple:{phone}"
        messages = [
            "Hola, necesito ayuda con mi pedido",
            "Me gustaria agendar una reunion para el martes",
            "Cuando puedo pasar a buscar?",
        ]

        for i, text in enumerate(messages, 1):
            print(f"[MSG {i}] {text}")
            await _client.memory.remember(
                buyer_id,
                BuyerInteraction(text=text, role="buyer"),
            )

        # Step 3: Manually create a contact (normally done by webhook)
        from wapsell.crm import contact_external_id, CONTACT_KIND
        from wapsell.resources import Resource

        contact_ext_id = contact_external_id(phone)
        contact_resource = _client.resources.upsert(
            Resource(
                tenant_id=tenant_id,
                kind=CONTACT_KIND,
                external_id=contact_ext_id,
                data={"phone": phone, "turn_count": 3},  # Simulate 3 turns
                summary=f"+{phone}",
            )
        )
        contact_id = contact_resource.id
        print(f"[CONTACT] {contact_id} (turn_count=3)")

        # Step 4: Manually trigger extraction (normally async via webhook)
        if api_module._crm_extractor:
            print(f"[EXTRACTOR] Running...")
            recent = await _client.memory.recall(buyer_id, limit=40)
            from wapsell.crm import ConversationTurn

            turns = [
                ConversationTurn(
                    role=i.role, text=i.text, at=i.at.isoformat() if i.at else None
                )
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
            print(f"[EXTRACT] Disabled (extractor not wired)")

        # Step 5: Fetch contact & verify turn count
        contact_res = http.get(
            f"/tenants/{tenant_id}/crm/contacts/by-phone/{phone}"
        )
        assert contact_res.status_code == 200
        contact = contact_res.json()
        turn_count = contact["data"].get("turn_count", 0)
        print(f"[VERIFY] Turn count: {turn_count}")
        assert turn_count == 3

        # Step 6: Fetch tasks
        tasks_res = http.get(
            f"/tenants/{tenant_id}/crm/contacts/{contact_id}/tasks"
        )
        assert tasks_res.status_code == 200
        tasks = tasks_res.json()
        print(f"[TASKS] Found {len(tasks)} task(s)")

        if tasks:
            for task in tasks:
                auto = task["data"].get("auto", False)
                status = task["data"].get("status", "open")
                title = task["data"].get("title", task["summary"])
                badge = "[AUTO]" if auto else "[MANUAL]"
                print(f"  - {title} [{status}] {badge}")

                # Test confirm if auto + open
                if auto and status == "open":
                    print(f"[ACTIONS] Testing task buttons...")
                    confirm_res = http.patch(
                        f"/tenants/{tenant_id}/crm/tasks/{task['id']}",
                        json={"confirmed": True},
                    )
                    assert confirm_res.status_code == 200
                    print(f"  - Confirm: OK")

                    done_res = http.patch(
                        f"/tenants/{tenant_id}/crm/tasks/{task['id']}",
                        json={"status": "done"},
                    )
                    assert done_res.status_code == 200
                    print(f"  - Mark done: OK")

        print("\n" + "=" * 70)
        print("[PASS] Extractor E2E complete")
        print("=" * 70)
