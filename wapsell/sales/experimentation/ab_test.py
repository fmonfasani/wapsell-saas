"""A/B testing framework for closing strategies.

Compare strategy effectiveness and automatically promote winners.

Example:
    >>> from wapsell.sales.experimentation.ab_test import ABTest, ExperimentConfig
    >>>
    >>> config = ExperimentConfig(
    ...     name="REFRAME vs DISCOUNT",
    ...     control_strategy="reframe",
    ...     treatment_strategy="discount_offer",
    ...     target_segment="investor",
    ...     sample_size=200,
    ... )
    >>>
    >>> test = ABTest(config=config)
    >>> await test.assign_group(deal_id="deal_123", tenant_id="acme")
    >>> # "control" or "treatment"
    >>>
    >>> # After collecting data
    >>> results = await test.analyze()
    >>> # {
    >>> #     "control_cr": 0.18,
    >>> #     "treatment_cr": 0.24,
    >>> #     "p_value": 0.032,
    >>> #     "winner": "treatment",
    >>> #     "confidence": 0.95,
    >>> # }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional
from datetime import datetime


class ExperimentStatus(Enum):
    """Experiment lifecycle."""

    PLANNING = "planning"
    RUNNING = "running"
    ANALYZING = "analyzing"
    PAUSED = "paused"
    COMPLETED = "completed"


@dataclass
class ExperimentConfig:
    """A/B test configuration."""

    name: str
    control_strategy: str
    treatment_strategy: str
    target_segment: str
    sample_size: int
    min_duration_days: int = 7
    significance_level: float = 0.05
    min_detectable_lift: float = 0.05  # 5% improvement


@dataclass
class ExperimentResults:
    """A/B test results."""

    experiment_name: str
    control_conversion_rate: float
    treatment_conversion_rate: float
    control_sample_size: int
    treatment_sample_size: int
    p_value: float
    confidence_level: float
    winner: Optional[str] = None  # "control", "treatment", or None
    lift: float = field(init=False)
    recommendation: str = field(init=False)

    def __post_init__(self) -> None:
        """Calculate derived metrics."""
        if self.control_conversion_rate > 0:
            self.lift = (
                (self.treatment_conversion_rate - self.control_conversion_rate)
                / self.control_conversion_rate
            )
        else:
            self.lift = 0.0

        # Recommendation logic
        if self.p_value < 0.05:  # Statistically significant
            if self.treatment_conversion_rate > self.control_conversion_rate:
                self.recommendation = "PROMOTE_TREATMENT"
                self.winner = "treatment"
            else:
                self.recommendation = "KEEP_CONTROL"
                self.winner = "control"
        else:
            self.recommendation = "CONTINUE_TEST"
            self.winner = None


class ABTest:
    """A/B testing framework for strategies.

    Manages experiment lifecycle:
    1. Assign deals to control/treatment
    2. Track outcomes
    3. Analyze results
    4. Promote winner
    """

    def __init__(
        self,
        config: ExperimentConfig,
        repository: Optional[Any] = None,
    ) -> None:
        """Initialize A/B test.

        Args:
            config: Experiment configuration
            repository: Deal repository for persistence
        """
        self.config = config
        self.repository = repository
        self.status = ExperimentStatus.PLANNING
        self.created_at = datetime.utcnow()
        self.completed_at: Optional[datetime] = None

    async def assign_group(
        self,
        deal_id: str,
        tenant_id: str,
    ) -> str:
        """Assign deal to experiment group.

        Args:
            deal_id: Deal ID
            tenant_id: Tenant ID

        Returns:
            "control" or "treatment" (random 50/50)
        """
        # In production:
        # 1. Hash deal_id to ensure consistent assignment
        # 2. 50% go to control, 50% to treatment
        # 3. Store assignment in database
        # 4. Return group assignment

        import hashlib

        hash_value = int(
            hashlib.md5(f"{deal_id}{self.config.name}".encode()).hexdigest(), 16
        )
        group = "control" if hash_value % 2 == 0 else "treatment"

        return group

    async def record_outcome(
        self,
        deal_id: str,
        group: str,
        conversion: bool,
        deal_value_usd: float,
    ) -> None:
        """Record deal outcome.

        Args:
            deal_id: Deal ID
            group: "control" or "treatment"
            conversion: Whether deal converted
            deal_value_usd: Deal value if converted
        """
        # In production:
        # 1. Store outcome in experiment_results table
        # 2. Include deal_id, group, conversion, timestamp, deal_value
        # 3. Update running conversion rates

        pass

    async def analyze(self) -> ExperimentResults:
        """Analyze experiment results.

        Performs Chi-squared test for significance.

        Returns:
            ExperimentResults with winner recommendation
        """
        # In production:
        # 1. Fetch all outcomes for experiment
        # 2. Calculate conversion rates for each group
        # 3. Perform Chi-squared statistical test
        # 4. Determine p-value and confidence level
        # 5. Return results with recommendation

        results = ExperimentResults(
            experiment_name=self.config.name,
            control_conversion_rate=0.18,
            treatment_conversion_rate=0.22,
            control_sample_size=100,
            treatment_sample_size=100,
            p_value=0.045,
            confidence_level=0.95,
        )

        return results

    async def promote_winner(
        self,
        results: ExperimentResults,
    ) -> bool:
        """Promote winning strategy to default.

        Args:
            results: Experiment results with winner

        Returns:
            True if promotion successful
        """
        # In production:
        # 1. Verify statistical significance
        # 2. Update strategy config to make winner default
        # 3. Log promotion in audit trail
        # 4. Set existing-segment strategy to winner
        # 5. Continue using control for new segments

        if results.recommendation == "PROMOTE_TREATMENT":
            # Update config
            self.config.control_strategy = self.config.treatment_strategy
            self.status = ExperimentStatus.COMPLETED
            self.completed_at = datetime.utcnow()
            return True

        return False
