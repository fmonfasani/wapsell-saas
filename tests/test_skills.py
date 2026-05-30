"""Tests for skills subsystem: catalog-lookup, lead-qualifier, sales-closer, registry, goal."""

from __future__ import annotations

import pytest

from waseller.goal import Goal, GoalJudge, GoalResult, GoalType
from waseller.ingestion.hindsight import InMemoryHindsight
from waseller.models import Fact
from waseller.skills.catalog_lookup import CatalogLookupSkill
from waseller.skills.lead_qualifier import LeadQualifierSkill
from waseller.skills.registry import SkillNotFoundError, SkillRegistry
from waseller.skills.sales_closer import SalesCloserSkill

pytestmark = pytest.mark.unit


class TestCatalogLookup:
    """Catalog-lookup is now Hindsight-backed; each test wires its own fixtures."""

    @pytest.fixture
    def populated(self) -> tuple[CatalogLookupSkill, str]:
        tenant_id = "tenant-a"
        hindsight = InMemoryHindsight()
        for content in (
            "name: Camiseta básica | price: 8500 | stock: 12",
            "name: Pantalón cargo | price: 21000 | stock: 5",
            "name: Mochila urbana | price: 15000 | stock: 8",
        ):
            hindsight.add_fact(Fact(tenant_id=tenant_id, source="catalog.csv", content=content))
        return CatalogLookupSkill(hindsight=hindsight), tenant_id

    async def test_finds_product_by_name(self, populated: tuple[CatalogLookupSkill, str]) -> None:
        skill, tenant = populated
        result = await skill.execute({"tenant_id": tenant}, {"query": "camiseta"})
        assert result.success
        assert len(result.data["matches"]) == 1
        assert "Camiseta básica" in result.data["matches"][0]["content"]
        assert result.data["matches"][0]["source"] == "catalog.csv"

    async def test_no_match_returns_empty(self, populated: tuple[CatalogLookupSkill, str]) -> None:
        skill, tenant = populated
        result = await skill.execute({"tenant_id": tenant}, {"query": "xyz-notfound"})
        assert result.success
        assert result.data["matches"] == []
        assert "no products found" in result.data["message"]

    async def test_empty_query_fails(self, populated: tuple[CatalogLookupSkill, str]) -> None:
        skill, _ = populated
        result = await skill.execute({"tenant_id": "x"}, {"query": ""})
        assert not result.success

    async def test_missing_tenant_id_fails(self, populated: tuple[CatalogLookupSkill, str]) -> None:
        skill, _ = populated
        result = await skill.execute({}, {"query": "camiseta"})
        assert not result.success
        assert result.error is not None and "tenant_id" in result.error

    async def test_only_returns_facts_for_requested_tenant(self) -> None:
        h = InMemoryHindsight()
        h.add_fact(Fact(tenant_id="A", source="a.csv", content="zapatillas rojas"))
        h.add_fact(Fact(tenant_id="B", source="b.csv", content="zapatillas azules"))
        skill = CatalogLookupSkill(hindsight=h)

        a = await skill.execute({"tenant_id": "A"}, {"query": "zapatillas"})
        b = await skill.execute({"tenant_id": "B"}, {"query": "zapatillas"})

        assert len(a.data["matches"]) == 1
        assert "rojas" in a.data["matches"][0]["content"]
        assert len(b.data["matches"]) == 1
        assert "azules" in b.data["matches"][0]["content"]

    async def test_top_k_param_limits_results(self) -> None:
        h = InMemoryHindsight()
        for i in range(10):
            h.add_fact(Fact(tenant_id="t", source="x", content=f"item-{i} test"))
        skill = CatalogLookupSkill(hindsight=h)

        result = await skill.execute({"tenant_id": "t"}, {"query": "test", "top_k": 3})
        assert len(result.data["matches"]) == 3


class TestLeadQualifier:
    @pytest.fixture
    def skill(self) -> LeadQualifierSkill:
        return LeadQualifierSkill()

    async def test_high_intent_message(self, skill: LeadQualifierSkill) -> None:
        result = await skill.execute(
            {}, {"message": "quiero comprar zapatillas urgentemente, cuánto cuestan?"}
        )
        assert result.success
        assert result.data["intent_score"] >= 70
        assert result.data["tag"] == "hot"

    async def test_low_intent_message(self, skill: LeadQualifierSkill) -> None:
        result = await skill.execute({}, {"message": "solo estoy viendo, tal vez después"})
        assert result.success
        assert result.data["intent_score"] < 40
        assert result.data["tag"] == "cold"

    async def test_mixed_signals(self, skill: LeadQualifierSkill) -> None:
        result = await skill.execute({}, {"message": "hola, precio de la mochila?"})
        assert result.success
        assert result.data["tag"] in ("warm", "hot")

    async def test_empty_message_fails(self, skill: LeadQualifierSkill) -> None:
        result = await skill.execute({}, {"message": ""})
        assert not result.success

    async def test_is_deterministic(self, skill: LeadQualifierSkill) -> None:
        msg = "necesito un presupuesto urgente"
        r1 = await skill.execute({}, {"message": msg})
        r2 = await skill.execute({}, {"message": msg})
        assert r1.data["intent_score"] == r2.data["intent_score"]


class TestSalesCloser:
    @pytest.fixture
    def skill(self) -> SalesCloserSkill:
        return SalesCloserSkill()

    async def test_starts_at_identify(self, skill: SalesCloserSkill) -> None:
        result = await skill.execute({}, {"current_stage": "IDENTIFY", "message": "hola"})
        assert result.success
        assert result.data["next_stage"] == "PRESENT"
        assert not result.data["is_terminal"]

    async def test_present_to_confirm(self, skill: SalesCloserSkill) -> None:
        result = await skill.execute(
            {}, {"current_stage": "PRESENT", "message": "me gusta, lo quiero"}
        )
        assert result.data["next_stage"] == "CONFIRM"

    async def test_present_to_objections(self, skill: SalesCloserSkill) -> None:
        result = await skill.execute({}, {"current_stage": "PRESENT", "message": "no, muy caro"})
        assert result.data["next_stage"] == "OBJECTIONS"

    async def test_full_close_flow(self, skill: SalesCloserSkill) -> None:
        # The expected next_stage sequence when starting at IDENTIFY and feeding
        # one message per step. Each iteration's `current` is the previous next.
        expected_next = ["PRESENT", "CONFIRM", "NOTIFY", "CLOSED"]
        messages = ["hola", "sí, quiero", "pagado", "gracias"]
        current = "IDENTIFY"
        for expected, msg in zip(expected_next, messages, strict=True):
            result = await skill.execute({}, {"current_stage": current, "message": msg})
            assert result.data["next_stage"] == expected
            current = result.data["next_stage"]
        assert result.data["is_terminal"]

    async def test_escalation(self, skill: SalesCloserSkill) -> None:
        result = await skill.execute(
            {}, {"current_stage": "OBJECTIONS", "message": "quiero hablar con un humano"}
        )
        assert result.data["next_stage"] == "ESCALATED"
        assert result.data["needs_escalation"]

    async def test_invalid_stage_fails(self, skill: SalesCloserSkill) -> None:
        result = await skill.execute({}, {"current_stage": "INVALID", "message": ""})
        assert not result.success


class TestSkillRegistry:
    @pytest.fixture
    def registry(self) -> SkillRegistry:
        return SkillRegistry()

    def test_lists_all_builtins(self, registry: SkillRegistry) -> None:
        names = registry.list()
        assert "catalog-lookup" in names
        assert "lead-qualifier" in names
        assert "sales-closer" in names

    def test_get_returns_skill(self, registry: SkillRegistry) -> None:
        skill = registry.get("catalog-lookup")
        assert skill.name == "catalog-lookup"

    def test_get_unknown_raises(self, registry: SkillRegistry) -> None:
        with pytest.raises(SkillNotFoundError):
            registry.get("nonexistent")

    async def test_invoke_dispatches_correctly(self, registry: SkillRegistry) -> None:
        result = await registry.invoke("lead-qualifier", {}, {"message": "quiero comprar"})
        assert result.success
        assert result.data["intent_score"] > 0


class TestGoal:
    def test_qualify_goal_with_high_intent(self) -> None:
        judge = GoalJudge()
        goal = Goal(goal_type=GoalType.QUALIFY, params={"message": "quiero comprar"})
        result = judge.judge(goal, {"intent_score": 80, "tag": "hot"})
        assert result.achieved
        assert result.score == 0.8

    def test_qualify_goal_with_low_intent(self) -> None:
        judge = GoalJudge()
        goal = Goal(goal_type=GoalType.QUALIFY, params={"message": "solo viendo"})
        result = judge.judge(goal, {"intent_score": 15, "tag": "cold"})
        assert not result.achieved
        assert result.score == 0.15

    def test_sell_goal_requires_payment(self) -> None:
        judge = GoalJudge()
        goal = Goal(goal_type=GoalType.SELL)
        result = judge.judge(goal, {"stage": "CLOSED", "payment_confirmed": True})
        assert result.achieved

    def test_sell_goal_fails_without_payment(self) -> None:
        judge = GoalJudge()
        goal = Goal(goal_type=GoalType.SELL)
        result = judge.judge(goal, {"stage": "CLOSED", "payment_confirmed": False})
        assert not result.achieved

    def test_lookup_goal_success(self) -> None:
        judge = GoalJudge()
        goal = Goal(goal_type=GoalType.LOOKUP, params={"query": "camiseta"})
        result = judge.judge(goal, {"matches": [{"name": "Camiseta"}]})
        assert result.achieved

    def test_lookup_goal_not_found(self) -> None:
        judge = GoalJudge()
        goal = Goal(goal_type=GoalType.LOOKUP, params={"query": "xyz"})
        result = judge.judge(goal, {"matches": []})
        assert not result.achieved

    def test_goal_to_dict(self) -> None:
        goal = Goal(tenant_id="t1", goal_type=GoalType.QUALIFY)
        d = goal.to_dict()
        assert d["goal_type"] == "qualify"
        assert d["tenant_id"] == "t1"
        assert d["status"] == "PENDING"

    def test_goal_result_to_dict(self) -> None:
        r = GoalResult(goal_id="g1", achieved=True, score=0.9, diagnostics={"key": "val"})
        d = r.to_dict()
        assert d["achieved"] is True
        assert d["score"] == 0.9
