"""SkillRegistry — discover and invoke skills by name."""

from __future__ import annotations

from typing import Any

from hermesell.skills.base import SkillBase, SkillResult
from hermesell.skills.catalog_lookup import CatalogLookupSkill
from hermesell.skills.lead_qualifier import LeadQualifierSkill
from hermesell.skills.sales_closer import SalesCloserSkill


class SkillNotFoundError(KeyError): ...


class SkillRegistry:
    """Registry of all available skills, keyed by skill.name."""

    def __init__(self) -> None:
        self._skills: dict[str, SkillBase] = {}
        self._register_builtins()

    def _register_builtins(self) -> None:
        for skill in (CatalogLookupSkill(), LeadQualifierSkill(), SalesCloserSkill()):
            self._skills[skill.name] = skill

    def register(self, skill: SkillBase) -> None:
        self._skills[skill.name] = skill

    def get(self, name: str) -> SkillBase:
        try:
            return self._skills[name]
        except KeyError:
            raise SkillNotFoundError(f"unknown skill: {name}") from None

    def list(self) -> list[str]:
        return list(self._skills)

    async def invoke(
        self, name: str, context: dict[str, Any], params: dict[str, Any]
    ) -> SkillResult:
        return await self.get(name).execute(context, params)
