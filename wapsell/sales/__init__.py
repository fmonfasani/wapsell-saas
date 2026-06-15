"""Sales infrastructure - Phase 2-3.

Production-grade infrastructure for multi-tenant sales automation:

**Phase 2: Infrastructure Layer**
  repositories/ - Postgres ORM + Redis caching
  celery_config - Async task queue + beat scheduler
  tasks/        - Async jobs (fine-tuning, metrics, escalations)
  dashboard/    - Admin analytics API
  ml/           - Per-tenant model fine-tuning
  experimentation/ - A/B testing framework

**Phase 3: Testing & Production**
  Comprehensive test suite (1,500+ LOC)
  Integration tests for end-to-end workflows
  Per-tenant isolation validation
"""

from __future__ import annotations

__all__: list[str] = []
