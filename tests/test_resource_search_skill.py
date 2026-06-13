"""Tests for ResourceSearchSkill (PR #37)."""

from __future__ import annotations

import pytest

from wapsell.resources import (
    InMemoryQueryLogRepository,
    InMemoryResourceRepository,
    Resource,
)
from wapsell.skills.resource_search import ResourceSearchSkill

pytestmark = pytest.mark.unit


def _resources() -> InMemoryResourceRepository:
    repo = InMemoryResourceRepository()
    repo.add(
        Resource(
            tenant_id="t1",
            kind="property",
            summary="2 amb Belgrano luminoso",
            data={"neighborhood": "Belgrano", "price": 145000, "bedrooms": 2},
        )
    )
    repo.add(
        Resource(
            tenant_id="t1",
            kind="property",
            summary="3 amb Palermo",
            data={"neighborhood": "Palermo", "price": 290000, "bedrooms": 3},
        )
    )
    repo.add(
        Resource(
            tenant_id="t1",
            kind="service",
            summary="tasación",
            data={"name": "Tasación", "price": 0},
        )
    )
    return repo


class TestResourceSearchSkill:
    async def test_fails_without_tenant_id(self) -> None:
        skill = ResourceSearchSkill()
        result = await skill.execute({}, {})
        assert result.success is False
        assert "tenant_id" in (result.error or "")

    async def test_filters_by_neighborhood(self) -> None:
        skill = ResourceSearchSkill(resources=_resources())
        result = await skill.execute(
            {"tenant_id": "t1"},
            {"filters": {"neighborhood": "Belgrano"}, "kind": "property"},
        )
        assert result.success is True
        matches = result.data["matches"]
        assert len(matches) == 1
        assert matches[0]["data"]["neighborhood"] == "Belgrano"

    async def test_filters_max_price(self) -> None:
        skill = ResourceSearchSkill(resources=_resources())
        result = await skill.execute(
            {"tenant_id": "t1"},
            {"filters": {"max_price": 200000}, "kind": "property"},
        )
        assert result.success is True
        prices = {m["data"]["price"] for m in result.data["matches"]}
        assert prices == {145000}

    async def test_free_text_query(self) -> None:
        skill = ResourceSearchSkill(resources=_resources())
        result = await skill.execute(
            {"tenant_id": "t1"},
            {"query": "luminoso"},
        )
        assert result.success is True
        matches = result.data["matches"]
        assert len(matches) == 1
        assert "luminoso" in matches[0]["summary"].lower()

    async def test_records_to_query_log(self) -> None:
        log = InMemoryQueryLogRepository()
        skill = ResourceSearchSkill(resources=_resources(), query_log=log)
        await skill.execute(
            {"tenant_id": "t1", "buyer_id": "demo:5491100"},
            {"filters": {"neighborhood": "Belgrano"}, "query": "luminoso"},
        )
        recent = log.list_recent("t1")
        assert len(recent) == 1
        assert recent[0].buyer_id == "demo:5491100"
        assert recent[0].filters == {"neighborhood": "Belgrano"}
        assert recent[0].query_text == "luminoso"

    async def test_limit_clamped(self) -> None:
        # No matter what limit the caller passes, the skill never returns
        # more than the configured max.
        skill = ResourceSearchSkill(resources=_resources())
        result = await skill.execute(
            {"tenant_id": "t1"},
            {"limit": 1000},
        )
        assert result.success is True
        assert len(result.data["matches"]) <= 25

    async def test_no_matches_returns_empty_with_message(self) -> None:
        skill = ResourceSearchSkill(resources=_resources())
        result = await skill.execute(
            {"tenant_id": "t1"},
            {"filters": {"neighborhood": "NonExistent"}},
        )
        assert result.success is True
        assert result.data["matches"] == []
        assert "no matches" in result.data["message"]

    async def test_registered_in_skill_registry(self) -> None:
        from wapsell.client import WapsellClient  # noqa: PLC0415

        client = WapsellClient()
        assert "resource-search" in client.skills.list()
