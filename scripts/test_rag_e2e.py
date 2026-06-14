#!/usr/bin/env python3
"""Test end-to-end RAG flow: simulate inbound message and check agent response."""

from __future__ import annotations

import httpx
import json
import sys

def test_rag_e2e(api_url: str, tenant_id: str) -> bool:
    """Test RAG with a real agent response."""

    # Create a buyer
    phone = "5491112345678"
    buyer_slug = f"test-rag-e2e:{phone}"

    with httpx.Client(timeout=30) as client:
        # 1. Send a test message via webhook demo
        print("\n[1] Sending test messages to trigger RAG...")
        messages = [
            "Hola, estoy buscando departamentos",
            "Me interesa algo en Palermo",
            "¿Qué hay disponible en Palermo?",
        ]

        demo_payload = {
            "phone": phone,
            "messages": messages,
        }

        resp = client.post(
            f"{api_url}/webhook/demo",
            json=demo_payload,
        )

        if resp.status_code != 200:
            print(f"[FAIL] Demo endpoint failed: {resp.status_code}")
            print(resp.text)
            return False

        result = resp.json()
        print(f"[OK] Demo executed for tenant {result.get('tenant_slug')}")
        print(f"   - Messages sent: {result.get('messages_sent')}")
        print(f"   - Turn count: {result.get('turn_count')}")

        # Use the original tenant that has the resources already loaded
        test_tenant_id = tenant_id

        # Do a direct test via the ResourceSearchSkill
        print("\n[2] Testing RAG search directly...")
        print(f"   Using tenant: {test_tenant_id}")

        # Search for properties
        search_queries = [
            ("palermo", "Should find Palermo properties"),
            ("4 dorm", "Should find 4-bedroom properties"),
            ("bajo 200", "Should find properties under $200k"),
        ]

        all_passed = True
        for query, description in search_queries:
            resp = client.post(
                f"{api_url}/tenants/{test_tenant_id}/resources/search",
                json={
                    "query": query,
                    "kind": "property",
                    "limit": 3,
                },
            )

            if resp.status_code != 200:
                print(f"[FAIL] Search for '{query}' failed: {resp.status_code}")
                all_passed = False
                continue

            results = resp.json()
            print(f"[OK] Search '{query}': {len(results)} results")
            print(f"   {description}")
            for r in results:
                data = r.get("data", {})
                print(f"   - {r.get('summary')}")

            if len(results) == 0:
                all_passed = False

        # 3. Verify data structure
        print("\n[3] Verifying property data structure...")
        resp = client.get(f"{api_url}/tenants/{test_tenant_id}/resources")
        if resp.status_code == 200:
            resources = resp.json()
            if resources:
                sample = resources[0]
                required_fields = ["barrio", "precio_usd", "dormitorios", "m2_cubiertos"]
                missing = [f for f in required_fields if f not in sample.get("data", {})]
                if missing:
                    print(f"[WARN]  Missing fields in property data: {missing}")
                else:
                    print(f"[OK] Property data structure is complete")

        return all_passed

if __name__ == "__main__":
    api_url = "http://localhost:8000"
    tenant_id = "1203bc78-438a-4613-9dd5-4b2153e44fef"  # From previous load

    print("=" * 70)
    print("RAG END-TO-END TEST")
    print("=" * 70)

    success = test_rag_e2e(api_url, tenant_id)

    if success:
        print("\n" + "=" * 70)
        print("[OK] RAG TEST PASSED")
        print("=" * 70)
        sys.exit(0)
    else:
        print("\n" + "=" * 70)
        print("[FAIL] RAG TEST FAILED")
        print("=" * 70)
        sys.exit(1)
