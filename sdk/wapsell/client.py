"""WapsellClient — the high-level SDK facade.

Thin orchestration over the subsystems (tenants, skills, agent, whatsapp).
"""

from __future__ import annotations

from typing import Any

from wapsell.agent.loop import AgentLoop
from wapsell.agent.soul import SoulConfig
from wapsell.crm import CrmRecorder
from wapsell.events.bus import EventBusPort, InMemoryEventBus
from wapsell.goal import Goal, GoalJudge, GoalResult
from wapsell.handoff import HandoffNotifierPort, NullHandoffNotifier
from wapsell.inbox import BotPausePort, InMemoryBotPauseRepository
from wapsell.ingestion.hindsight import HindsightPort, InMemoryHindsight
from wapsell.ingestion.preprocessor import Preprocessor
from wapsell.llm.port import EchoLLM, LLMPort
from wapsell.memory.buyer import BuyerMemoryPort, InMemoryBuyerMemory
from wapsell.models import Tenant
from wapsell.onboarding.flow import OnboardingFlow
from wapsell.resources import (
    DataSourceRepositoryPort,
    InMemoryDataSourceRepository,
    InMemoryQueryLogRepository,
    InMemoryResourceRepository,
    LearningService,
    QueryLogPort,
    ResourceRepositoryPort,
    ResourceSynchronizer,
)
from wapsell.skills.registry import SkillRegistry
from wapsell.templates import (
    InMemoryTemplateRepository,
    TemplateRepositoryPort,
)
from wapsell.tenant import (
    InMemoryTenantRepository,
    InMemoryTenantSpawner,
    TenantManager,
    TenantRepositoryPort,
    TenantRouter,
    TenantSpawner,
    TenantSupervisor,
)
from wapsell.whatsapp.gateway import InMemoryGateway, WhatsAppGatewayPort


def buyer_id_for(tenant_slug: str, from_number: str) -> str:
    """Canonical buyer_id composition. Centralized so namespacing is consistent."""
    return f"{tenant_slug}:{from_number}"


class WapsellClient:
    """Entrypoint for operating a Wapsell deployment.

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
        event_bus: EventBusPort | None = None,
        llm: LLMPort | None = None,
        templates: TemplateRepositoryPort | None = None,
        handoff_notifier: HandoffNotifierPort | None = None,
        bot_pauses: BotPausePort | None = None,
        resources: ResourceRepositoryPort | None = None,
        data_sources: DataSourceRepositoryPort | None = None,
        query_log: QueryLogPort | None = None,
    ) -> None:
        self._repo: TenantRepositoryPort = repository or InMemoryTenantRepository()
        self._spawner: TenantSpawner = spawner or InMemoryTenantSpawner()
        self._hindsight: HindsightPort = hindsight or InMemoryHindsight()
        self._memory: BuyerMemoryPort = memory or InMemoryBuyerMemory()
        self._gateway: WhatsAppGatewayPort = gateway or InMemoryGateway()
        self._event_bus: EventBusPort = event_bus or InMemoryEventBus()
        # EchoLLM is the safe default: deterministic, no network calls. Production
        # wiring injects OpenRouterLLM (or any LLMPort) from the composition root.
        self._llm: LLMPort = llm or EchoLLM()
        self._templates: TemplateRepositoryPort = templates or InMemoryTemplateRepository()
        # NullHandoffNotifier is the safe default: no network calls, no
        # surprises in tests. Composition root injects HttpHandoffNotifier
        # in production so configured per-tenant webhooks actually fire.
        self._handoff_notifier: HandoffNotifierPort = handoff_notifier or NullHandoffNotifier()
        # Bot-pause registry — checked by the webhook handler before agent
        # dispatch; written by the handoff branch and the dashboard "take
        # over" actions. InMemory by default; Postgres in prod via env wire.
        self._bot_pauses: BotPausePort = bot_pauses or InMemoryBotPauseRepository()
        # Agnostic data layer (PR #35): resources + data sources + query log.
        # Composition root picks Postgres in prod via env wire.
        self._resources: ResourceRepositoryPort = resources or InMemoryResourceRepository()
        self._data_sources: DataSourceRepositoryPort = (
            data_sources or InMemoryDataSourceRepository()
        )
        self._query_log: QueryLogPort = query_log or InMemoryQueryLogRepository()
        # Synchronizer wires resources + sources for the sync endpoint. The
        # HTTP client used by adapters defaults to a per-call AsyncClient;
        # callers can inject a shared one for connection reuse.
        self._synchronizer = ResourceSynchronizer(
            resources=self._resources,
            data_sources=self._data_sources,
        )
        # Learning service (PR #38) reads from the same backing stores so
        # the SOUL hints reflect what the dashboard already shows.
        self._learning = LearningService(
            resources=self._resources,
            query_log=self._query_log,
        )
        # CRM recorder (PR #43) — find-or-create contact + append activity
        # on every WhatsApp turn. Sits on the same resources port so the
        # dashboard /crm/contacts page reads what the webhook handler wrote.
        self._crm = CrmRecorder(resources=self._resources)
        self.tenants = TenantManager(spawner=self._spawner, repository=self._repo)
        self.router = TenantRouter(self._repo)
        self.supervisor = TenantSupervisor(self._repo, self._spawner)
        self.preprocessor = Preprocessor(hindsight=self._hindsight)
        self.skills = SkillRegistry(
            hindsight=self._hindsight,
            resources=self._resources,
            query_log=self._query_log,
        )
        self.onboarding = OnboardingFlow(self.tenants, self.supervisor, event_bus=self._event_bus)
        self.agent = AgentLoop(
            memory=self._memory,
            hindsight=self._hindsight,
            llm=self._llm,
            learning=self._learning,
            resources=self._resources,
        )
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

    @property
    def event_bus(self) -> EventBusPort:
        return self._event_bus

    @property
    def llm(self) -> LLMPort:
        return self._llm

    @property
    def templates(self) -> TemplateRepositoryPort:
        return self._templates

    @property
    def handoff_notifier(self) -> HandoffNotifierPort:
        return self._handoff_notifier

    @property
    def bot_pauses(self) -> BotPausePort:
        return self._bot_pauses

    @property
    def resources(self) -> ResourceRepositoryPort:
        return self._resources

    @property
    def data_sources(self) -> DataSourceRepositoryPort:
        return self._data_sources

    @property
    def query_log(self) -> QueryLogPort:
        return self._query_log

    @property
    def synchronizer(self) -> ResourceSynchronizer:
        return self._synchronizer

    @property
    def learning(self) -> LearningService:
        return self._learning

    @property
    def crm(self) -> CrmRecorder:
        return self._crm

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
