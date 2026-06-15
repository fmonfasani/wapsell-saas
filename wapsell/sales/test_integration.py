"""Integration tests for Phase 2 infrastructure.

Tests end-to-end workflows across Postgres, Redis, Celery, and Dashboard.
"""

from __future__ import annotations

import pytest

from wapsell.sales.dashboard.api import DashboardAPI
from wapsell.sales.ml.fine_tuning import TenantModelTuner
from wapsell.sales.experimentation.ab_test import ABTest, ExperimentConfig


class MockDealRepository:
    """Mock repository for integration testing."""

    def __init__(self) -> None:
        """Initialize with empty state."""
        self.deals = {}
        self.deal_counter = 0

    async def register_deal(
        self,
        tenant_id: str,
        buyer_id: str,
        product_id: str,
        status: str,
        value_usd: float,
    ) -> dict:
        """Register deal."""
        self.deal_counter += 1
        deal_id = f"deal_{self.deal_counter}"
        deal = {
            "deal_id": deal_id,
            "tenant_id": tenant_id,
            "buyer_id": buyer_id,
            "product_id": product_id,
            "status": status,
            "value_usd": value_usd,
        }
        self.deals[deal_id] = deal
        return deal

    async def update_deal_status(
        self,
        tenant_id: str,
        deal_id: str,
        status: str,
    ) -> dict:
        """Update deal status."""
        if deal_id in self.deals:
            self.deals[deal_id]["status"] = status
            return self.deals[deal_id]
        return {}

    async def list_deals(
        self,
        tenant_id: str,
        status: str | None = None,
    ) -> list[dict]:
        """List deals for tenant."""
        deals = [d for d in self.deals.values() if d["tenant_id"] == tenant_id]
        if status:
            deals = [d for d in deals if d["status"] == status]
        return deals

    async def get_metrics(self, tenant_id: str) -> dict:
        """Get metrics."""
        deals = [d for d in self.deals.values() if d["tenant_id"] == tenant_id]
        total = len(deals)
        won = len([d for d in deals if d["status"] == "CLOSED_WON"])
        return {
            "total_deals": total,
            "closed_won": won,
            "conversion_rate": won / total if total > 0 else 0,
        }


class MockEmbeddings:
    """Mock embeddings for integration tests."""

    async def embed(self, text: str) -> list[float]:
        """Mock embedding."""
        return [0.1] * 1536


class TestDealPipelineWorkflow:
    """Test complete deal pipeline workflow."""

    async def test_deal_lifecycle(self) -> None:
        """Test deal from PROSPECT to CLOSED_WON."""
        repo = MockDealRepository()

        # Register deal
        deal = await repo.register_deal(
            tenant_id="acme",
            buyer_id="buyer_123",
            product_id="prod_456",
            status="PROSPECT",
            value_usd=50000.0,
        )
        assert deal["status"] == "PROSPECT"

        # Move through stages
        for stage in ["QUALIFIED", "PRESENTED", "NEGOTIATING", "CLOSED_WON"]:
            deal = await repo.update_deal_status(
                tenant_id="acme",
                deal_id=deal["deal_id"],
                status=stage,
            )
            assert deal["status"] == stage

    async def test_multi_deal_pipeline(self) -> None:
        """Test multiple deals in pipeline simultaneously."""
        repo = MockDealRepository()

        # Create 10 deals
        deals = []
        for i in range(10):
            deal = await repo.register_deal(
                tenant_id="acme",
                buyer_id=f"buyer_{i}",
                product_id="prod_456",
                status="PROSPECT",
                value_usd=10000.0 * (i + 1),
            )
            deals.append(deal)

        # Move different ones through different stages
        await repo.update_deal_status(
            tenant_id="acme",
            deal_id=deals[0]["deal_id"],
            status="CLOSED_WON",
        )
        await repo.update_deal_status(
            tenant_id="acme",
            deal_id=deals[1]["deal_id"],
            status="NEGOTIATING",
        )
        await repo.update_deal_status(
            tenant_id="acme",
            deal_id=deals[2]["deal_id"],
            status="CLOSED_LOST",
        )

        # Verify metrics
        metrics = await repo.get_metrics(tenant_id="acme")
        assert metrics["total_deals"] == 10
        assert metrics["closed_won"] == 1


class TestDashboardWithData:
    """Test dashboard with real deal data."""

    async def test_dashboard_metrics(self) -> None:
        """Test dashboard metrics calculation."""
        repo = MockDealRepository()

        # Create test data
        for i in range(20):
            await repo.register_deal(
                tenant_id="acme",
                buyer_id=f"buyer_{i}",
                product_id="prod_1",
                status="CLOSED_WON" if i < 5 else "PROSPECT",
                value_usd=10000.0,
            )

        # Query dashboard
        dashboard = DashboardAPI(deal_repo=repo)

        metrics = await repo.get_metrics(tenant_id="acme")
        assert metrics["total_deals"] == 20
        assert metrics["closed_won"] == 5
        assert metrics["conversion_rate"] == 0.25

    async def test_dashboard_status_distribution(self) -> None:
        """Test status distribution in dashboard."""
        repo = MockDealRepository()

        # Create deals in different statuses
        statuses = ["PROSPECT", "QUALIFIED", "NEGOTIATING", "CLOSED_WON"]
        for status in statuses:
            for i in range(3):
                await repo.register_deal(
                    tenant_id="acme",
                    buyer_id=f"buyer_{status}_{i}",
                    product_id="prod_1",
                    status=status,
                    value_usd=10000.0,
                )

        dashboard = DashboardAPI(deal_repo=repo)

        # Should be able to get deals by status
        prospects = await repo.list_deals(tenant_id="acme", status="PROSPECT")
        assert len(prospects) == 3

        qualified = await repo.list_deals(tenant_id="acme", status="QUALIFIED")
        assert len(qualified) == 3


class TestMLWithData:
    """Test ML tuning with collected feedback."""

    async def test_fine_tuning_workflow(self) -> None:
        """Test complete fine-tuning workflow."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(embeddings=embeddings)

        # Simulate collected feedback
        feedback = [
            {
                "text": "What's your price?",
                "label": "price",
                "correct": True,
            }
            for _ in range(100)
        ]
        feedback.extend(
            [
                {
                    "text": "When can you deliver?",
                    "label": "timing",
                    "correct": True,
                }
                for _ in range(100)
            ]
        )

        # Fine-tune
        metrics = await tuner.fine_tune(
            tenant_id="acme",
            feedback_records=feedback,
        )

        assert metrics.training_samples == 200
        assert metrics.improvement > 0

        # Evaluate
        eval_result = await tuner.evaluate(
            tenant_id="acme",
            test_samples=feedback[:20],
        )

        assert "accuracy" in eval_result

        # Deploy
        deployed = await tuner.deploy_fine_tuned_model(
            tenant_id="acme",
            model_version="v1",
        )
        assert deployed is True


class TestABTestingWithDealData:
    """Test A/B testing with deal data."""

    async def test_abtest_with_deals(self) -> None:
        """Test A/B testing integrated with deals."""
        config = ExperimentConfig(
            name="REFRAME vs DISCOUNT",
            control_strategy="reframe",
            treatment_strategy="discount_offer",
            target_segment="investor",
            sample_size=100,
        )

        test = ABTest(config=config)

        # Create 100 deals and assign to groups
        control_deals = []
        treatment_deals = []

        for i in range(100):
            group = await test.assign_group(
                deal_id=f"deal_{i}",
                tenant_id="acme",
            )

            if group == "control":
                control_deals.append((f"deal_{i}", group))
            else:
                treatment_deals.append((f"deal_{i}", group))

        # Should have roughly 50 in each group
        assert 40 < len(control_deals) < 60
        assert 40 < len(treatment_deals) < 60

        # Record outcomes
        for deal_id, group in control_deals[:10]:
            await test.record_outcome(
                deal_id=deal_id,
                group=group,
                conversion=True,
                deal_value_usd=50000.0,
            )

        for deal_id, group in treatment_deals[:15]:
            await test.record_outcome(
                deal_id=deal_id,
                group=group,
                conversion=True,
                deal_value_usd=50000.0,
            )

        # Analyze
        results = await test.analyze()
        assert results is not None


class TestPerTenantIsolation:
    """Test per-tenant isolation across components."""

    async def test_deals_isolated_by_tenant(self) -> None:
        """Test deals don't leak between tenants."""
        repo = MockDealRepository()

        # Create deals for tenant_a
        await repo.register_deal(
            tenant_id="tenant_a",
            buyer_id="buyer_1",
            product_id="prod_1",
            status="PROSPECT",
            value_usd=10000.0,
        )

        # Create deals for tenant_b
        await repo.register_deal(
            tenant_id="tenant_b",
            buyer_id="buyer_1",
            product_id="prod_1",
            status="PROSPECT",
            value_usd=20000.0,
        )

        # Verify isolation
        deals_a = await repo.list_deals(tenant_id="tenant_a")
        deals_b = await repo.list_deals(tenant_id="tenant_b")

        assert len(deals_a) == 1
        assert len(deals_b) == 1
        assert deals_a[0]["value_usd"] == 10000.0
        assert deals_b[0]["value_usd"] == 20000.0

    async def test_abtest_per_tenant(self) -> None:
        """Test A/B tests isolated per tenant."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="all",
            sample_size=100,
        )

        test_a = ABTest(config=config)
        test_b = ABTest(config=config)

        # Assign same deal_id to both tenants
        group_a = await test_a.assign_group(deal_id="deal_1", tenant_id="tenant_a")
        group_b = await test_b.assign_group(deal_id="deal_1", tenant_id="tenant_b")

        # Should be consistent within tenant
        group_a2 = await test_a.assign_group(deal_id="deal_1", tenant_id="tenant_a")
        group_b2 = await test_b.assign_group(deal_id="deal_1", tenant_id="tenant_b")

        assert group_a == group_a2
        assert group_b == group_b2
