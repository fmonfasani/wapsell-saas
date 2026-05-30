"""hermesell CLI (argparse — dependency-free).

hermesell tenant-create --name "Acme" --slug acme
hermesell soul --name "Acme" --slug acme
hermesell skills list
hermesell goal --type qualify --message "quiero comprar zapatillas"
"""

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from hermesell.client import HermesSellClient
from hermesell.goal import Goal, GoalType
from hermesell.skills.lead_qualifier import LeadQualifierSkill

T = TypeVar("T")


def _run_async(coro: Awaitable[T]) -> T:
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


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

    skills_parser = sub.add_parser("skills", help="List or invoke skills")
    skills_parser.add_argument("action", choices=["list", "invoke"], nargs="?")
    skills_parser.add_argument("--skill", default=None)
    skills_parser.add_argument("--message", default=None)

    goal_parser = sub.add_parser("goal", help="Create and evaluate a goal")
    goal_parser.add_argument("--type", choices=[t.value for t in GoalType], default="qualify")
    goal_parser.add_argument("--message", default="", help="Inbound message to evaluate")
    goal_parser.add_argument("--tenant", default="default")

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

    if args.command == "skills":
        if args.action == "list" or not args.action:
            for name in client.list_skills():
                print(name)
            return 0
        if args.action == "invoke":
            if not args.skill:
                print("error: --skill required for invoke")
                return 1
            invoke_result = _run_async(
                client.invoke_skill(args.skill, {}, {"message": args.message or ""})
            )
            print(invoke_result)
            return 0
        return 1

    if args.command == "goal":
        skill = LeadQualifierSkill()
        skill_result = _run_async(skill.execute({}, {"message": args.message}))
        if not skill_result.success:
            print(f"error: {skill_result.error}")
            return 1
        goal = Goal(
            tenant_id=args.tenant, goal_type=GoalType(args.type), params={"message": args.message}
        )
        judge_result = client._judge.judge(goal, skill_result.data)
        print(f"goal: {goal.goal_type} -> {'ACHIEVED' if judge_result.achieved else 'PENDING'}")
        print(f"score: {judge_result.score}")
        print(f"data:  {skill_result.data}")
        return 0

    return 1


if __name__ == "__main__":
    raise SystemExit(main())
