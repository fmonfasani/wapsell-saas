"""Tests for A/B testing framework.

Tests experiment lifecycle, assignment, analysis, and winner promotion.
"""

from __future__ import annotations

import pytest

from wapsell.sales.experimentation.ab_test import (
    ABTest,
    ExperimentConfig,
    ExperimentResults,
    ExperimentStatus,
)


class TestExperimentConfig:
    """Test ExperimentConfig."""

    def test_config_initialization(self) -> None:
        """Test config creation."""
        config = ExperimentConfig(
            name="REFRAME vs DISCOUNT",
            control_strategy="reframe",
            treatment_strategy="discount_offer",
            target_segment="investor",
            sample_size=200,
        )

        assert config.name == "REFRAME vs DISCOUNT"
        assert config.control_strategy == "reframe"
        assert config.treatment_strategy == "discount_offer"
        assert config.sample_size == 200
        assert config.significance_level == 0.05

    def test_config_custom_significance_level(self) -> None:
        """Test custom significance level."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
            significance_level=0.01,
        )

        assert config.significance_level == 0.01


class TestExperimentStatus:
    """Test ExperimentStatus enum."""

    def test_status_values(self) -> None:
        """Test all status values."""
        assert ExperimentStatus.PLANNING.value == "planning"
        assert ExperimentStatus.RUNNING.value == "running"
        assert ExperimentStatus.ANALYZING.value == "analyzing"
        assert ExperimentStatus.PAUSED.value == "paused"
        assert ExperimentStatus.COMPLETED.value == "completed"


class TestExperimentResults:
    """Test ExperimentResults."""

    def test_results_initialization(self) -> None:
        """Test results creation."""
        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.18,
            treatment_conversion_rate=0.22,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.045,
            confidence_level=0.95,
        )

        assert results.experiment_name == "Test"
        assert results.control_conversion_rate == 0.18
        assert results.treatment_conversion_rate == 0.22

    def test_lift_calculation(self) -> None:
        """Test lift calculation."""
        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.20,
            treatment_conversion_rate=0.24,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.045,
            confidence_level=0.95,
        )

        # (0.24 - 0.20) / 0.20 = 0.20 (20% lift)
        assert abs(results.lift - 0.20) < 0.001

    def test_lift_zero_control_rate(self) -> None:
        """Test lift when control rate is zero."""
        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.0,
            treatment_conversion_rate=0.10,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.045,
            confidence_level=0.95,
        )

        assert results.lift == 0.0

    def test_recommendation_promote_treatment(self) -> None:
        """Test recommendation when treatment wins."""
        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.18,
            treatment_conversion_rate=0.22,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.03,  # < 0.05, significant
            confidence_level=0.97,
        )

        assert results.recommendation == "PROMOTE_TREATMENT"
        assert results.winner == "treatment"

    def test_recommendation_keep_control(self) -> None:
        """Test recommendation when control wins."""
        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.22,
            treatment_conversion_rate=0.18,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.03,  # < 0.05, significant
            confidence_level=0.97,
        )

        assert results.recommendation == "KEEP_CONTROL"
        assert results.winner == "control"

    def test_recommendation_continue_test(self) -> None:
        """Test recommendation when not significant."""
        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.20,
            treatment_conversion_rate=0.22,
            control_sample_size=50,
            treatment_sample_size=50,
            p_value=0.15,  # > 0.05, not significant
            confidence_level=0.85,
        )

        assert results.recommendation == "CONTINUE_TEST"
        assert results.winner is None


class TestABTest:
    """Test ABTest class."""

    async def test_abtest_initialization(self) -> None:
        """Test ABTest initialization."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
        )

        test = ABTest(config=config)

        assert test.config == config
        assert test.status == ExperimentStatus.PLANNING
        assert test.completed_at is None

    async def test_assign_group_consistency(self) -> None:
        """Test consistent group assignment (idempotent)."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
        )

        test = ABTest(config=config)

        # Same deal should always get same group
        group1 = await test.assign_group(deal_id="deal_123", tenant_id="acme")
        group2 = await test.assign_group(deal_id="deal_123", tenant_id="acme")

        assert group1 == group2
        assert group1 in ["control", "treatment"]

    async def test_assign_group_distribution(self) -> None:
        """Test roughly 50/50 distribution."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=200,
        )

        test = ABTest(config=config)

        control_count = 0
        treatment_count = 0

        for i in range(100):
            group = await test.assign_group(
                deal_id=f"deal_{i}",
                tenant_id="acme",
            )
            if group == "control":
                control_count += 1
            else:
                treatment_count += 1

        # Should be close to 50/50
        total = control_count + treatment_count
        control_pct = control_count / total
        treatment_pct = treatment_count / total

        # Allow 40-60% range
        assert 0.4 < control_pct < 0.6
        assert 0.4 < treatment_pct < 0.6

    async def test_record_outcome(self) -> None:
        """Test recording outcome."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
        )

        test = ABTest(config=config)

        # Should not raise
        await test.record_outcome(
            deal_id="deal_123",
            group="control",
            conversion=True,
            deal_value_usd=50000.0,
        )

    async def test_analyze_returns_results(self) -> None:
        """Test analyze returns ExperimentResults."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
        )

        test = ABTest(config=config)

        results = await test.analyze()

        assert isinstance(results, ExperimentResults)
        assert results.experiment_name == "Test"
        assert results.p_value >= 0
        assert results.confidence_level >= 0

    async def test_promote_winner_updates_status(self) -> None:
        """Test promote_winner updates status."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
        )

        test = ABTest(config=config)

        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.18,
            treatment_conversion_rate=0.24,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.03,
            confidence_level=0.97,
        )

        promoted = await test.promote_winner(results)

        assert promoted is True
        assert test.status == ExperimentStatus.COMPLETED
        assert test.completed_at is not None

    async def test_promote_winner_no_promotion_if_not_significant(self) -> None:
        """Test promote_winner doesn't promote if not significant."""
        config = ExperimentConfig(
            name="Test",
            control_strategy="a",
            treatment_strategy="b",
            target_segment="segment",
            sample_size=100,
        )

        test = ABTest(config=config)

        results = ExperimentResults(
            experiment_name="Test",
            control_conversion_rate=0.20,
            treatment_conversion_rate=0.22,
            control_sample_size=50,
            treatment_sample_size=50,
            p_value=0.15,
            confidence_level=0.85,
        )

        promoted = await test.promote_winner(results)

        assert promoted is False
        assert test.status != ExperimentStatus.COMPLETED

    async def test_full_experiment_workflow(self) -> None:
        """Test complete experiment workflow."""
        config = ExperimentConfig(
            name="REFRAME vs DISCOUNT",
            control_strategy="reframe",
            treatment_strategy="discount_offer",
            target_segment="investor",
            sample_size=100,
        )

        test = ABTest(config=config)

        # Step 1: Assign deals
        group1 = await test.assign_group(deal_id="deal_1", tenant_id="acme")
        group2 = await test.assign_group(deal_id="deal_2", tenant_id="acme")
        assert group1 in ["control", "treatment"]
        assert group2 in ["control", "treatment"]

        # Step 2: Record outcomes
        await test.record_outcome(
            deal_id="deal_1",
            group=group1,
            conversion=True,
            deal_value_usd=50000.0,
        )
        await test.record_outcome(
            deal_id="deal_2",
            group=group2,
            conversion=False,
            deal_value_usd=0.0,
        )

        # Step 3: Analyze
        results = await test.analyze()
        assert isinstance(results, ExperimentResults)

        # Step 4: Promote if winner
        if results.recommendation == "PROMOTE_TREATMENT":
            promoted = await test.promote_winner(results)
            assert promoted is True
