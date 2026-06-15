"""A/B testing framework for sales strategies.

Experimental features for comparing and optimizing closing strategies.

Structure:
  ab_test.py - A/B testing framework
"""

from __future__ import annotations

from wapsell.sales.experimentation.ab_test import (
    ABTest,
    ExperimentConfig,
    ExperimentResults,
    ExperimentStatus,
)

__all__ = [
    "ExperimentConfig",
    "ExperimentStatus",
    "ExperimentResults",
    "ABTest",
]
