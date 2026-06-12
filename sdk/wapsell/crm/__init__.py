"""CRM subsystem — contacts + activities + (later) deals + tasks + pipelines.

Phase 1: contact + activity helpers. The CRM rides on top of the existing
:mod:`wapsell.resources` data layer — there is no separate CRM table.
Every CRM entity is a ``Resource`` with a specific ``kind`` value:

- ``kind="contact"``  → one buyer profile (phone, name, tags, intent_score)
- ``kind="activity"`` → one timeline event (whatsapp_message, note, call, ...)
- ``kind="deal"``     → (Phase 3) opportunity with stage + value
- ``kind="task"``     → (Phase 4) to-do with due_at + owner
- ``kind="pipeline"`` → (Phase 3) per-tenant pipeline config

This module exposes a thin orchestration layer
(:class:`CrmRecorder`) that the webhook handler calls on every inbound +
outbound WhatsApp turn. The recorder finds-or-creates the contact, updates
its turn counters + last_seen + profile name, and appends one activity
linked to it.

Design plan: ``docs/PLAN-CRM.md``.
"""

from __future__ import annotations

from wapsell.crm.recorder import (
    ACTIVITY_KIND,
    CONTACT_KIND,
    CrmRecorder,
    contact_external_id,
)

__all__ = [
    "ACTIVITY_KIND",
    "CONTACT_KIND",
    "CrmRecorder",
    "contact_external_id",
]
