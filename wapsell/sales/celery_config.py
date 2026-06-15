"""Celery configuration for sales task queue.

Enables async processing of heavy ML workloads:
- Batch objection detection
- ML model fine-tuning
- Metrics aggregation
- Escalation notifications

Uses Redis as both broker and result backend.

Example:
    >>> from wapsell.sales.celery_config import app, init_celery
    >>> from wapsell.sales.tasks import detect_objections_batch
    >>>
    >>> # Initialize with Flask/FastAPI app
    >>> init_celery(app)
    >>>
    >>> # Queue async task
    >>> task = detect_objections_batch.delay(
    ...     tenant_id="acme",
    ...     messages=["too expensive", "can't do now"],
    ... )
    >>>
    >>> # Poll result
    >>> result = task.get(timeout=30)
"""

from __future__ import annotations

from celery import Celery
from kombu import Exchange, Queue

# ============================================================================
# Celery app
# ============================================================================

app = Celery("wapsell.sales")

# Configuration
app.conf.update(
    broker_url="redis://localhost:6379/0",
    result_backend="redis://localhost:6379/1",
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=30 * 60,  # 30 minutes hard limit
    task_soft_time_limit=25 * 60,  # 25 minutes soft limit (send SoftTimeLimitExceeded)
    result_expires=3600,  # Results expire after 1 hour
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
)

# Task routing
app.conf.task_routes = {
    "wapsell.sales.tasks.objection_detection.*": {"queue": "ml"},
    "wapsell.sales.tasks.fine_tuning.*": {"queue": "ml"},
    "wapsell.sales.tasks.metrics.*": {"queue": "analytics"},
    "wapsell.sales.tasks.notifications.*": {"queue": "notifications"},
}

# Queue definitions
app.conf.task_queues = (
    Queue(
        "ml",
        exchange=Exchange("ml", type="direct"),
        routing_key="ml",
        priority=10,
    ),
    Queue(
        "analytics",
        exchange=Exchange("analytics", type="direct"),
        routing_key="analytics",
        priority=5,
    ),
    Queue(
        "notifications",
        exchange=Exchange("notifications", type="direct"),
        routing_key="notifications",
        priority=8,
    ),
)

# Scheduled tasks (Celery beat)
from celery.schedules import crontab

app.conf.beat_schedule = {
    # Run daily at 2 AM UTC
    "fine-tune-models-daily": {
        "task": "wapsell.sales.tasks.fine_tuning.fine_tune_all_tenants",
        "schedule": crontab(hour=2, minute=0),
        "options": {"queue": "ml"},
    },
    # Run every hour
    "calculate-metrics-hourly": {
        "task": "wapsell.sales.tasks.metrics.calculate_metrics_all_tenants",
        "schedule": crontab(minute=0),
        "options": {"queue": "analytics"},
    },
    # Run every 30 minutes
    "check-escalations": {
        "task": "wapsell.sales.tasks.notifications.check_escalations",
        "schedule": crontab(minute="*/30"),
        "options": {"queue": "notifications"},
    },
}


# ============================================================================
# Initialization
# ============================================================================


def init_celery(app_context) -> None:
    """Initialize Celery with Flask/FastAPI app.

    Args:
        app_context: Flask app or FastAPI app instance

    Example:
        >>> from fastapi import FastAPI
        >>> from wapsell.sales.celery_config import init_celery
        >>>
        >>> app = FastAPI()
        >>> init_celery(app)
    """
    class ContextTask(app.Task):
        """Celery task that runs in app context."""

        def __call__(self, *args, **kwargs):
            with app_context.app_context():
                return self.run(*args, **kwargs)

    app.Task = ContextTask


# ============================================================================
# Task base classes
# ============================================================================


class TaskConfig:
    """Base configuration for tasks."""

    autoretry_for = (Exception,)
    retry_kwargs = {"max_retries": 3}
    retry_backoff = True
    retry_backoff_max = 600
    retry_jitter = True
