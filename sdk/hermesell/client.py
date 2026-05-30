"""HermesSellClient — the high-level SDK facade.

Thin orchestration over the subsystems (tenants, skills, agent, whatsapp).
"""

from __future__ import annotations

from typing import Any

from hermesell.agent.soul import SoulConfig
from hermesell.goal import Goal, GoalJudge, GoalResult
from hermesell.ingestion.hindsight import HindsightPort, InMemoryHindsight
from hermesell.ingestion.preprocessor import Preprocessor
from hermesell.models import Tenant
from hermesell.skills.registry import SkillRegistry
from hermesell.tenant import (
    InMemoryTenantRepository,
    InMemoryTenantSpawner,
    TenantManager,
    TenantRepositoryPort,
    TenantRouter,
    TenantSpawner,
    TenantSupervisor,
)


class HermesSellClient:
    """Entrypoint for operating a HermesSell deployment.

    All subsystems share the same backing stores: creating a tenant via
    ``tenants.create`` makes it routable via ``router.resolve``; ingesting a
    file via ``preprocessor.process`` makes its facts queryable via the
    ``catalog-lookup`` skill — no manual plumbing needed.
    """

    def __init__(
        self,
        *,
        spawner: TenantSpawner | None = None,
        repository: TenantRepositoryPort | None = None,
        hindsight: HindsightPort | None = None,
    ) -> None:
        self._repo: TenantRepositoryPort = repository or InMemoryTenantRepository()
        self._spawner: TenantSpawner = spawner or InMemoryTenantSpawner()
        self._hindsight: HindsightPort = hindsight or InMemoryHindsight()
        self.tenants = TenantManager(spawner=self._spawner, repository=self._repo)
        self.router = TenantRouter(self._repo)
        self.supervisor = TenantSupervisor(self._repo, self._spawner)
        self.preprocessor = Preprocessor(hindsight=self._hindsight)
        self.skills = SkillRegistry(hindsight=self._hindsight)
        self._judge = GoalJudge()

    @property
    def hindsight(self) -> HindsightPort:
        return self._hindsight

    def create_tenant(self, name: str, slug: str, *, model: str | None = None) -> Tenant:
        return self.tenants.create(name, slug, model=model)

    def soul_for(self, tenant_id: str, config: SoulConfig | None = None) -> str:
        return self.tenants.render_soul(tenant_id, config)

    def list_skills(self) -> list[str]:
        return self.skills.list()

    async def invoke_skill(
        self, name: str, context: dict[str, Any], params: dict[str, Any]
    ) -> dict[str, Any]:
        result = await self.skills.invoke(name, context, params)
        return result.data | {"success": result.success, "error": result.error}

    async def run_goal(self, goal: Goal, context: dict[str, Any]) -> GoalResult:
        return self._judge.judge(goal, context)
