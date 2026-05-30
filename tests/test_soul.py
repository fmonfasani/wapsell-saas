"""Tests for SOUL rendering and tenant management."""

from __future__ import annotations

import pytest

from waseller import SoulConfig, TenantManager, TenantStatus, WasellerClient

pytestmark = pytest.mark.unit


def test_soul_is_deterministic_and_contains_name() -> None:
    mgr = TenantManager()
    t = mgr.create("Acme Store", "acme")
    soul_a = mgr.render_soul(t.id)
    soul_b = mgr.render_soul(t.id)
    assert soul_a == soul_b
    assert "Acme Store" in soul_a
    assert "Nunca inventes stock ni precios." in soul_a


def test_soul_includes_skills_section() -> None:
    mgr = TenantManager()
    t = mgr.create("Acme Store", "acme")
    soul = mgr.render_soul(t.id)
    assert "catalog-lookup" in soul
    assert "lead-qualifier" in soul
    assert "sales-closer" in soul


def test_soul_skills_can_be_omitted() -> None:
    mgr = TenantManager()
    t = mgr.create("Acme", "acme")
    soul = mgr.render_soul(t.id, SoulConfig(include_skills=False))
    assert "catalog-lookup" not in soul


def test_soul_respects_custom_config() -> None:
    mgr = TenantManager()
    t = mgr.create("Acme", "acme")
    soul = mgr.render_soul(t.id, SoulConfig(language="English", tone="formal"))
    assert "English" in soul
    assert "formal" in soul


def test_duplicate_slug_rejected() -> None:
    mgr = TenantManager()
    mgr.create("Acme", "acme")
    with pytest.raises(ValueError, match="slug already exists"):
        mgr.create("Acme 2", "acme")


async def test_activate_transitions_status() -> None:
    mgr = TenantManager()
    t = mgr.create("Acme", "acme")
    assert t.status is TenantStatus.PROVISIONING
    activated = await mgr.activate(t.id)
    assert activated.status is TenantStatus.ACTIVE


def test_client_facade_creates_and_renders() -> None:
    client = WasellerClient()
    t = client.create_tenant("Tienda", "tienda")
    assert "Tienda" in client.soul_for(t.id)
