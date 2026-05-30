"""WasellerClient — the high-level SDK facade.

Thin orchestration over the subsystems (tenants, skills, agent, whatsapp).
"""

from __future__ import annotations

from typing import Any

from waseller.agent.soul import SoulConfig
from waseller.goal import Goal, GoalJudge, GoalResult
from waseller.ingestion.hindsight import HindsightPort, InMemoryHindsight
from waseller.ingestion.preprocessor import Preprocessor
from waseller.memory.buyer import BuyerMemoryPort, InMemoryBuyerMemory
from waseller.models import Tenant
from waseller.skills.registry import SkillRegistry
from waseller.tenant import (
    InMemoryTenantRepository,
    InMemoryTenantSpawner,
    TenantManager,
    TenantRepositoryPort,
    TenantRouter,
    TenantSpawner,
    TenantSupervisor,
)
from waseller.whatsapp.gateway import InMemoryGateway, WhatsAppGatewayPort


def buyer_id_for(tenant_slug: str, from_number: str) -> str:
    """Canonical buyer_id composition. Centralized so namespacing is consistent."""
    return f"{tenant_slug}:{from_number}"


class WasellerClient:
    """Entrypoint for operating a Waseller deployment.

    All subsystems share the same backing stores: creating a tenant via
    ``tenants.create`` makes it routable via ``router.resolve``; ingesting a
    file via ``preprocessor.process`` makes its facts queryable via the
    ``catalog-lookup`` skill; remembering an interaction via ``memory.remember``
    makes it visible to the next agent turn; sending via ``gateway.send_text``
    goes through the WhatsApp adapter (Kapso in prod, in-memory in tests).
    """

    def __init__(
        self,
        *,
        spawner: TenantSpawner | None = None,
        repository: TenantRepositoryPort | None = None,
        hindsight: HindsightPort | None = None,
        memory: BuyerMemoryPort | None = None,
        gateway: WhatsAppGatewayPort | None = None,
    ) -> None:
        self._repo: TenantRepositoryPort = repository or InMemoryTenantRepository()
        self._spawner: TenantSpawner = spawner or InMemoryTenantSpawner()
        self._hindsight: HindsightPort = hindsight or InMemoryHindsight()
        self._memory: BuyerMemoryPort = memory or InMemoryBuyerMemory()
        self._gateway: WhatsAppGatewayPort = gateway or InMemoryGateway()
        self.tenants = TenantManager(spawner=self._spawner, repository=self._repo)
        self.router = TenantRouter(self._repo)
        self.supervisor = TenantSupervisor(self._repo, self._spawner)
        self.preprocessor = Preprocessor(hindsight=self._hindsight)
        self.skills = SkillRegistry(hindsight=self._hindsight)
        self._judge = GoalJudge()

    @property
    def hindsight(self) -> HindsightPort:
        return self._hindsight

    @property
    def memory(self) -> BuyerMemoryPort:
        return self._memory

    @property
    def gateway(self) -> WhatsAppGatewayPort:
        return self._gateway

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
