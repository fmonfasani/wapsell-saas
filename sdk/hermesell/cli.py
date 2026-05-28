"""hermesell CLI (argparse — dependency-free).

hermesell tenant-create --name "Acme" --slug acme
hermesell soul --name "Acme" --slug acme
"""

from __future__ import annotations

import argparse

from hermesell.client import HermesSellClient


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="hermesell", description="HermesSell control CLI")
    sub = parser.add_subparsers(dest="command", required=True)

    create = sub.add_parser("tenant-create", help="Create a tenant")
    create.add_argument("--name", required=True)
    create.add_argument("--slug", required=True)
    create.add_argument("--model", default=None)

    soul = sub.add_parser("soul", help="Render a tenant's SOUL.md")
    soul.add_argument("--name", required=True)
    soul.add_argument("--slug", required=True)

    args = parser.parse_args(argv)
    client = HermesSellClient()

    if args.command == "tenant-create":
        tenant = client.create_tenant(args.name, args.slug, model=args.model)
        print(f"created tenant {tenant.id} ({tenant.slug})")
        return 0
    if args.command == "soul":
        tenant = client.create_tenant(args.name, args.slug)
        print(client.soul_for(tenant.id))
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
