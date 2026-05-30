"""SkillRegistry — discover and invoke skills by name."""

from __future__ import annotations

from typing import Any

from waseller.ingestion.hindsight import HindsightPort
from waseller.skills.base import SkillBase, SkillResult
from waseller.skills.catalog_lookup import CatalogLookupSkill
from waseller.skills.lead_qualifier import LeadQualifierSkill
from waseller.skills.sales_closer import SalesCloserSkill


class SkillNotFoundError(KeyError): ...


class SkillRegistry:
    """Registry of all available skills, keyed by ``skill.name``."""

    def __init__(self, *, hindsight: HindsightPort | None = None) -> None:
        self._skills: dict[str, SkillBase] = {}
        self._register_builtins(hindsight)

    def _register_builtins(self, hindsight: HindsightPort | None) -> None:
        for skill in (
            CatalogLookupSkill(hindsight=hindsight),
            LeadQualifierSkill(),
            SalesCloserSkill(),
        ):
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
