"""Tests for Celery tasks."""

from __future__ import annotations

import pytest
from unittest.mock import patch, MagicMock

from wapsell.sales.celery_config import app
from wapsell.sales.tasks.objection_detection import (
    detect_objections_batch,
    detect_objections_for_tenant,
)
from wapsell.sales.tasks.fine_tuning import (
    fine_tune_tenant,
    fine_tune_all_tenants,
)
from wapsell.sales.tasks.metrics import (
    calculate_metrics_for_tenant,
    calculate_metrics_all_tenants,
)
from wapsell.sales.tasks.notifications import (
    notify_escalation,
    check_escalations,
)


@pytest.fixture
def celery_config():
    """Configure Celery for testing."""
    app.conf.update(
        task_always_eager=True,  # Execute tasks synchronously in tests
        task_eager_propagates=True,  # Propagate exceptions
    )
    return app


class TestObjectionDetectionTasks:
    """Test objection detection tasks."""

    def test_detect_objections_batch_signature(self, celery_config):
        """Task has correct signature."""
        assert detect_objections_batch.name == "wapsell.sales.tasks.objection_detection.detect_objections_batch"

    def test_detect_objections_for_tenant_signature(self, celery_config):
        """Task has correct signature."""
        assert (
            detect_objections_for_tenant.name
            == "wapsell.sales.tasks.objection_detection.detect_objections_for_tenant"
        )

    def test_detect_objections_batch_returns_list(self, celery_config):
        """Batch detection returns list of results."""
        with patch("wapsell.sales.tasks.objection_detection.ObjectionDetector"):
            result = detect_objections_batch(
                tenant_id="acme",
                messages=["too expensive", "can't do now"],
            )
            assert isinstance(result, list)


class TestFineTuningTasks:
    """Test fine-tuning tasks."""

    def test_fine_tune_tenant_returns_dict(self, celery_config):
        """Fine-tune task returns metrics dict."""
        result = fine_tune_tenant(tenant_id="acme")
        assert isinstance(result, dict)
        assert "tenant_id" in result
        assert result["tenant_id"] == "acme"

    def test_fine_tune_all_tenants_returns_summary(self, celery_config):
        """Batch fine-tune returns summary."""
        result = fine_tune_all_tenants()
        assert isinstance(result, dict)
        assert "timestamp" in result
        assert "tenants_processed" in result


class TestMetricsTasks:
    """Test metrics tasks."""

    def test_calculate_metrics_for_tenant_returns_dict(self, celery_config):
        """Metrics calculation returns dict."""
        result = calculate_metrics_for_tenant(
            tenant_id="acme",
            window_days=30,
        )
        assert isinstance(result, dict)
        assert result["tenant_id"] == "acme"
        assert result["window_days"] == 30

    def test_calculate_metrics_all_tenants_returns_summary(self, celery_config):
        """Batch metrics returns summary."""
        result = calculate_metrics_all_tenants()
        assert isinstance(result, dict)
        assert "timestamp" in result
        assert "tenants_processed" in result


class TestNotificationTasks:
    """Test notification tasks."""

    def test_notify_escalation_returns_dict(self, celery_config):
        """Escalation notification returns dict."""
        result = notify_escalation(
            tenant_id="acme",
            deal_id="deal_123",
            reason="max_objections_exceeded",
        )
        assert isinstance(result, dict)
        assert result["deal_id"] == "deal_123"
        assert result["reason"] == "max_objections_exceeded"

    def test_check_escalations_returns_summary(self, celery_config):
        """Escalation check returns summary."""
        result = check_escalations()
        assert isinstance(result, dict)
        assert "timestamp" in result
        assert "escalations_found" in result


class TestTaskQueue:
    """Test queue configuration."""

    def test_queues_are_defined(self):
        """Task queues are properly defined."""
        queues = app.conf.task_queues
        queue_names = [q.name for q in queues]

        assert "ml" in queue_names
        assert "analytics" in queue_names
        assert "notifications" in queue_names

    def test_task_routes_are_configured(self):
        """Task routing is configured."""
        routes = app.conf.task_routes
        assert "wapsell.sales.tasks.objection_detection.*" in routes
        assert "wapsell.sales.tasks.fine_tuning.*" in routes
        assert "wapsell.sales.tasks.metrics.*" in routes


class TestScheduledTasks:
    """Test scheduled task (beat) configuration."""

    def test_beat_schedule_is_configured(self):
        """Beat schedule is properly configured."""
        schedule = app.conf.beat_schedule

        assert "fine-tune-models-daily" in schedule
        assert "calculate-metrics-hourly" in schedule
        assert "check-escalations" in schedule

    def test_fine_tune_runs_daily(self):
        """Fine-tune task is scheduled daily."""
        schedule = app.conf.beat_schedule
        fine_tune = schedule["fine-tune-models-daily"]

        assert fine_tune["task"] == "wapsell.sales.tasks.fine_tuning.fine_tune_all_tenants"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
