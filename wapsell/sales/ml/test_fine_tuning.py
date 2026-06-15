"""Tests for ML fine-tuning.

Tests model tuning, evaluation, and deployment.
"""

from __future__ import annotations

import pytest

from wapsell.sales.ml.fine_tuning import FineTuneMetrics, TenantModelTuner


class MockEmbeddings:
    """Mock embeddings provider."""

    async def embed(self, text: str) -> list[float]:
        """Mock embedding."""
        return [0.1] * 1536


class TestFineTuneMetrics:
    """Test FineTuneMetrics dataclass."""

    def test_metrics_initialization(self) -> None:
        """Test metrics initialization."""
        metrics = FineTuneMetrics(
            tenant_id="acme",
            training_samples=100,
            validation_samples=25,
            accuracy_before=0.85,
            accuracy_after=0.91,
        )

        assert metrics.tenant_id == "acme"
        assert metrics.training_samples == 100
        assert metrics.improvement == 0.06

    def test_metrics_no_improvement(self) -> None:
        """Test metrics with no improvement."""
        metrics = FineTuneMetrics(
            tenant_id="acme",
            training_samples=100,
            validation_samples=25,
            accuracy_before=0.85,
            accuracy_after=0.85,
        )

        assert metrics.improvement == 0.0

    def test_metrics_negative_improvement(self) -> None:
        """Test metrics with regression."""
        metrics = FineTuneMetrics(
            tenant_id="acme",
            training_samples=100,
            validation_samples=25,
            accuracy_before=0.91,
            accuracy_after=0.85,
        )

        assert metrics.improvement == -0.06


class TestTenantModelTuner:
    """Test TenantModelTuner."""

    async def test_tuner_initialization(self) -> None:
        """Test tuner initialization."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(
            embeddings=embeddings,
            learning_rate=0.001,
            max_epochs=10,
            batch_size=32,
        )

        assert tuner.learning_rate == 0.001
        assert tuner.max_epochs == 10
        assert tuner.batch_size == 32

    async def test_fine_tune_returns_metrics(self) -> None:
        """Test fine_tune returns FineTuneMetrics."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(embeddings=embeddings)

        feedback = [
            {
                "text": "What is your price?",
                "label": "price",
                "correct": True,
            },
            {
                "text": "When can you deliver?",
                "label": "timing",
                "correct": True,
            },
        ]

        metrics = await tuner.fine_tune(
            tenant_id="acme",
            feedback_records=feedback,
        )

        assert isinstance(metrics, FineTuneMetrics)
        assert metrics.tenant_id == "acme"
        assert metrics.improvement > 0

    async def test_fine_tune_with_large_feedback(self) -> None:
        """Test fine_tune with many feedback records."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(embeddings=embeddings)

        # Generate 500 feedback records
        feedback = [
            {
                "text": f"Sample {i}",
                "label": "price" if i % 2 == 0 else "timing",
                "correct": True,
            }
            for i in range(500)
        ]

        metrics = await tuner.fine_tune(
            tenant_id="acme",
            feedback_records=feedback,
        )

        assert metrics.training_samples == 500

    async def test_evaluate_returns_dict(self) -> None:
        """Test evaluate returns metrics dict."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(embeddings=embeddings)

        test_samples = [
            {"text": "Sample 1", "label": "price"},
            {"text": "Sample 2", "label": "timing"},
        ]

        result = await tuner.evaluate(
            tenant_id="acme",
            test_samples=test_samples,
        )

        assert isinstance(result, dict)
        assert "accuracy" in result
        assert "precision" in result
        assert "recall" in result
        assert "f1" in result

    async def test_deploy_fine_tuned_model(self) -> None:
        """Test model deployment."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(embeddings=embeddings)

        result = await tuner.deploy_fine_tuned_model(
            tenant_id="acme",
            model_version="v1",
        )

        assert result is True

    async def test_full_fine_tuning_workflow(self) -> None:
        """Test complete fine-tuning workflow."""
        embeddings = MockEmbeddings()
        tuner = TenantModelTuner(embeddings=embeddings)

        # Step 1: Fine-tune
        feedback = [
            {"text": f"Sample {i}", "label": "price", "correct": True}
            for i in range(50)
        ]
        metrics = await tuner.fine_tune(
            tenant_id="acme",
            feedback_records=feedback,
        )
        assert metrics.improvement > 0

        # Step 2: Evaluate
        eval_results = await tuner.evaluate(
            tenant_id="acme",
            test_samples=feedback[:10],
        )
        assert eval_results["accuracy"] >= 0

        # Step 3: Deploy
        deployed = await tuner.deploy_fine_tuned_model(
            tenant_id="acme",
            model_version="v1",
        )
        assert deployed is True
