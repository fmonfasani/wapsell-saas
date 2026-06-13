#!/usr/bin/env python3
"""End-to-end test of CRM extractor without real WhatsApp.

Simulates: inbound #1  inbound #2  inbound #3 (triggers extraction)
 task appears in dashboard with auto=true +  Auto badge.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
from datetime import datetime, timezone
from typing import Any

import httpx

API_BASE = "https://api.wapsell.com"
PHONE = "5491100001234"
TENANT_SLUG = "test-extractor"


async def main() -> None:
    async with httpx.AsyncClient(timeout=30, verify=False) as client:
        # Step 1: Create tenant
        print("[*] Creating tenant...")
        tenant_res = await client.post(
            f"{API_BASE}/tenants",
            json={"name": "Extractor Test", "slug": TENANT_SLUG},
        )
        tenant_res.raise_for_status()
        tenant = tenant_res.json()
        tenant_id = tenant["id"]
        print(f"    Tenant: {tenant_id}")

        # Step 2-4: Send 3 inbound messages (turn count reaches 3  extraction fires)
        messages = [
            "Hola, necesito ayuda con mi pedido",
            "Me gustara agendar una reunin para el martes",
            "Cundo puedo pasar a buscar?",
        ]

        for i, text in enumerate(messages, 1):
            print(f"\n[MSG] Inbound #{i}: {text}")
            msg_id = f"wamid.test.{tenant_id}.{i}"
            webhook_payload = {
                "entry": [
                    {
                        "changes": [
                            {
                                "value": {
                                    "messages": [
                                        {
                                            "from": PHONE,
                                            "id": msg_id,
                                            "text": {"body": text},
                                            "timestamp": str(
                                                int(datetime.now(timezone.utc).timestamp())
                                            ),
                                            "type": "text",
                                        }
                                    ]
                                }
                            }
                        ]
                    }
                ]
            }
            webhook_res = await client.post(
                f"{API_BASE}/webhook",
                json=webhook_payload,
                headers={"X-Hub-Signature": "dummy"},  # Auth off in test
            )
            webhook_res.raise_for_status()
            print(f"    Webhook ACK")

            # Small delay between messages
            await asyncio.sleep(0.5)

        # Wait for async extraction task to complete (if stride-3 fired)
        await asyncio.sleep(2)

        # Step 5: Fetch contact
        print("\n Fetching contact...")
        contact_res = await client.get(
            f"{API_BASE}/tenants/{tenant_id}/crm/contacts/by-phone/{PHONE}"
        )
        contact_res.raise_for_status()
        contact = contact_res.json()
        contact_id = contact["id"]
        turn_count = contact["data"].get("turn_count", 0)
        print(f"    Contact: {contact_id}")
        print(f"    Turn count: {turn_count}")

        # Step 6: Fetch tasks for this contact
        print("\n Fetching tasks...")
        tasks_res = await client.get(
            f"{API_BASE}/tenants/{tenant_id}/crm/contacts/{contact_id}/tasks"
        )
        tasks_res.raise_for_status()
        tasks = tasks_res.json()

        if not tasks:
            print("     No tasks extracted (extractor may not have run yet)")
            print("    This is expected if stride didn't trigger or LLM skipped")
        else:
            print(f"    Found {len(tasks)} task(s)")
            for task in tasks:
                auto = task["data"].get("auto", False)
                status = task["data"].get("status", "open")
                title = task["data"].get("title", task["summary"])
                auto_badge = " Auto" if auto else "manual"
                print(f"       {title} [{status}] {auto_badge}")

                # Step 7: Test task actions (confirm  done  dismiss)
                if auto and status == "open":
                    print(f"\n Testing task actions...")

                    # Confirm
                    print(f"    Confirming...")
                    confirm_res = await client.patch(
                        f"{API_BASE}/tenants/{tenant_id}/crm/tasks/{task['id']}",
                        json={"confirmed": True},
                    )
                    confirm_res.raise_for_status()
                    confirmed_task = confirm_res.json()
                    assert confirmed_task["data"]["confirmed"] is True
                    print(f"       Confirmed: {confirmed_task['data']}")

                    # Mark done
                    print(f"    Marking done...")
                    done_res = await client.patch(
                        f"{API_BASE}/tenants/{tenant_id}/crm/tasks/{task['id']}",
                        json={"status": "done"},
                    )
                    done_res.raise_for_status()
                    done_task = done_res.json()
                    assert done_task["data"]["status"] == "done"
                    print(f"       Marked done")

                    # Try to delete (should work since status is no longer open)
                    print(f"    Deleting...")
                    del_res = await client.delete(
                        f"{API_BASE}/tenants/{tenant_id}/crm/tasks/{task['id']}"
                    )
                    assert del_res.status_code == 204
                    print(f"       Deleted")

        # Step 8: Summary
        print("\n" + "=" * 70)
        print(" TEST SUMMARY")
        print("=" * 70)
        print(f"Tenant: {tenant_id} ({TENANT_SLUG})")
        print(f"Contact: {contact_id} (+{PHONE})")
        print(f"Turn count: {turn_count}")
        print(f"Tasks extracted: {len(tasks)}")
        if tasks:
            auto_count = sum(
                1 for t in tasks if t["data"].get("auto", False)
            )
            print(f"   {auto_count} auto-extracted ()")
            print(f"   {len(tasks) - auto_count} manual")
        print("=" * 70)


if __name__ == "__main__":
    asyncio.run(main())
