"""Wapsell SDK QuickStart — 10-minute intro to building a sales agent.

Run this file to see Wapsell in action:
    python examples/quickstart.py

No credentials needed — uses in-memory storage and deterministic LLM.
"""

import asyncio

from wapsell import WapsellClient, buyer_id_for
from wapsell.models import Fact


async def main() -> None:
    """Build a simple real-estate sales agent in 10 lines of code."""

    # 1. Create client (all in-memory, no setup needed)
    print("[1] Creating Wapsell client...")
    client = WapsellClient.local()

    # 2. Create a tenant (a "sales agent" for a business)
    print("[2] Creating tenant 'Acme Realty'...")
    tenant = client.tenants.create(
        name="Acme Realty",
        slug="acme",
    )
    print(f"    OK: Tenant created: {tenant.slug}")

    # 3. Ingest a product catalog (facts that the agent will know about)
    print("[3] Ingesting property catalog...")
    properties = [
        {
            "id": "prop-001",
            "type": "apartment",
            "bedrooms": 2,
            "bathrooms": 1,
            "price_usd": 150000,
            "location": "Downtown",
            "description": "Modern 2br apartment with city view",
        },
        {
            "id": "prop-002",
            "type": "apartment",
            "bedrooms": 3,
            "bathrooms": 2,
            "price_usd": 250000,
            "location": "Beach",
            "description": "Luxury 3br apartment with ocean view",
        },
        {
            "id": "prop-003",
            "type": "house",
            "bedrooms": 4,
            "bathrooms": 2,
            "price_usd": 350000,
            "location": "Suburbs",
            "description": "Spacious family house with garden",
        },
    ]

    for prop in properties:
        fact = Fact(
            tenant_id=tenant.id,
            source="catalog",
            content=str(prop),  # In prod, structured ingestion via file/API
        )
        client.hindsight.add_fact(fact)
    print(f"    OK: Ingested {len(properties)} properties")

    # 4. Simulate buyer messages (the agent learns from the conversation)
    print("\n[4] Simulating buyer conversation...\n")

    buyer_number = "+5491234567"
    buyer_id = buyer_id_for(tenant.slug, buyer_number)

    # First message: buyer states their needs
    msg1 = "Hola, busco un departamento de 2 ambientes hasta 200 mil dólares"
    print(f"BUYER: {msg1}")

    response1 = await client.agent.respond(
        tenant=tenant,
        buyer_id=buyer_id,
        message=msg1,
    )
    print(f"AGENT: {response1.reply}\n")

    # Second message: follow-up question
    msg2 = "¿Ese de Downtown tiene cochera?"
    print(f"BUYER: {msg2}")

    response2 = await client.agent.respond(
        tenant=tenant,
        buyer_id=buyer_id,
        message=msg2,
    )
    print(f"AGENT: {response2.reply}\n")

    # 5. Show what the agent "knows"
    print("[5] Agent knowledge:")
    print(f"   - Tenant: {tenant.name} ({tenant.slug})")
    print(f"   - Catalog size: {len(properties)} properties")
    print(f"   - Conversation turns: 2")
    print(f"   - Buyer ID: {buyer_id}")

    print("\n[OK] QuickStart complete!")
    print("\n[INFO] Next steps:")
    print("   - Swap WapsellClient.local() for WapsellClient.production(...)")
    print("   - Integrate with your WhatsApp number via Meta API")
    print("   - Deploy to your infrastructure (Docker, VPS, Lambda, etc.)")


if __name__ == "__main__":
    asyncio.run(main())
