#!/usr/bin/env python3
"""Load real estate catalog (100 departamentos) into Wapsell resources via HTTP API.

Usage:
    python scripts/load_inmo_catalog.py [--api-url URL] [--json-file PATH] [--tenant-slug SLUG]

Example:
    python scripts/load_inmo_catalog.py --api-url http://localhost:8000 --json-file scripts/100_departamentos.json
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

import httpx

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger(__name__)


def load_catalog(
    api_url: str,
    json_file: str,
    tenant_slug: str = "inmo1",
) -> None:
    """Load catalog JSON into resources via HTTP API."""

    with httpx.Client(timeout=30) as client:
        # 1. Get or create tenant
        logger.info(f"Looking for tenant: {tenant_slug}")
        resp = client.get(f"{api_url}/tenants")
        if resp.status_code != 200:
            logger.error(f"Failed to list tenants: {resp.status_code}")
            sys.exit(1)

        tenants = resp.json()
        tenant = next((t for t in tenants if t.get("slug") == tenant_slug), None)

        if not tenant:
            logger.info(f"Creating tenant: {tenant_slug}")
            resp = client.post(
                f"{api_url}/tenants",
                json={
                    "name": "Inmo1",
                    "slug": tenant_slug,
                    "model": "inmobiliario",
                },
            )
            if resp.status_code != 201:
                logger.error(f"Failed to create tenant: {resp.status_code}")
                logger.error(resp.text)
                sys.exit(1)
            tenant = resp.json()

        tenant_id = tenant["id"]
        logger.info(f"Using tenant: {tenant_id} ({tenant_slug})")

        # 2. Load JSON
        logger.info(f"Loading JSON: {json_file}")
        with open(json_file) as f:
            properties = json.load(f)
        logger.info(f"Loaded {len(properties)} properties")

        # 3. Create Resources via API
        logger.info("Inserting resources...")
        created = 0
        errors = 0
        for prop in properties:
            summary = (
                f"{prop.get('dormitorios', 0)} dorm, "
                f"{prop.get('barrio', '?')}, "
                f"USD {prop.get('precio_usd', 0):,.0f}"
            )
            resp = client.post(
                f"{api_url}/tenants/{tenant_id}/resources",
                json={
                    "kind": "property",
                    "external_id": f"property-{prop['id']}",
                    "data": prop,
                    "summary": summary,
                },
            )
            if resp.status_code not in (200, 201):
                logger.warning(f"Failed to create resource {prop['id']}: {resp.status_code}")
                errors += 1
            else:
                created += 1
                if created % 10 == 0:
                    logger.info(f"  ... {created}/{len(properties)}")

        logger.info(f"✅ Loaded {created} resources ({errors} errors)")

        # 4. Test search
        logger.info("Testing search...")
        resp = client.post(
            f"{api_url}/tenants/{tenant_id}/resources/search",
            json={
                "query": "Palermo bajo 200 mil",
                "kind": "property",
                "limit": 5,
            },
        )
        if resp.status_code == 200:
            results = resp.json()
            logger.info(f"Search returned {len(results)} results:")
            for r in results:
                print(f"  - {r['summary']}")
        else:
            logger.warning(f"Search failed: {resp.status_code}")

        logger.info("✅ Done!")


def main() -> None:
    parser = argparse.ArgumentParser(description="Load Inmo catalog via HTTP API")
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000",
        help="Wapsell API URL (default: http://localhost:8000)",
    )
    parser.add_argument(
        "--json-file",
        default="scripts/100_departamentos.json",
        help="Path to properties JSON",
    )
    parser.add_argument(
        "--tenant-slug",
        default="inmo1",
        help="Tenant slug (default: inmo1)",
    )

    args = parser.parse_args()

    # Resolve JSON path
    json_file = Path(args.json_file)
    if not json_file.is_absolute():
        # Try relative to current directory first, then relative to script location
        if not json_file.exists():
            alt_path = Path(__file__).parent / json_file.name
            if alt_path.exists():
                json_file = alt_path

    if not json_file.exists():
        logger.error(f"File not found: {json_file}")
        sys.exit(1)

    logger.info(f"API URL: {args.api_url}")
    load_catalog(args.api_url, str(json_file), args.tenant_slug)


if __name__ == "__main__":
    main()
