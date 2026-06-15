"""Celery tasks for sales automation.

Async tasks for heavy ML workloads:
- Batch objection detection
- Model fine-tuning
- Metrics calculation
- Notifications

Structure:
  objection_detection.py - Detect objections in batches
  fine_tuning.py - Fine-tune ML models per tenant
  metrics.py - Calculate metrics aggregates
  notifications.py - Send escalation alerts
"""

from __future__ import annotations

from wapsell.sales.tasks.objection_detection import (
    detect_objections_batch,
    detect_objections_for_tenant,
)
from wapsell.sales.tasks.fine_tuning import (
    fine_tune_all_tenants,
    fine_tune_tenant,
)
from wapsell.sales.tasks.metrics import (
    calculate_metrics_all_tenants,
    calculate_metrics_for_tenant,
)
from wapsell.sales.tasks.notifications import (
    check_escalations,
    notify_escalation,
)

__all__ = [
    # Objection detection
    "detect_objections_batch",
    "detect_objections_for_tenant",
    # Fine-tuning
    "fine_tune_all_tenants",
    "fine_tune_tenant",
    # Metrics
    "calculate_metrics_all_tenants",
    "calculate_metrics_for_tenant",
    # Notifications
    "check_escalations",
    "notify_escalation",
]
