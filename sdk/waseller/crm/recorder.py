"""CrmRecorder — find-or-create contacts + append activities on every turn.

The webhook handler calls this object on every inbound WhatsApp message and
every outbound agent reply. It maintains two resource kinds on top of the
existing :mod:`waseller.resources` data layer:

- A ``contact`` per (tenant, phone). First inbound creates it; every
  subsequent turn bumps ``turn_count`` and ``last_seen_at`` + (re-)sets the
  profile name if WhatsApp surfaced one.
- An ``activity`` per turn. ``external_id`` is the message_id (for inbound)
  or a deterministic outbound suffix, so retries from Meta don't create
  duplicates.

Errors here are best-effort — the recorder never blocks the agent reply
path. Callers wrap calls in ``try/except`` and log warnings, mirroring the
pattern used by the existing handoff notifier and bot-pause registry.

This module knows nothing about the dashboard, the agent, or the LLM. It's
pure persistence orchestration so the same code can be invoked from the
webhook handler, from a CSV importer, or from a future API endpoint that
records manual activities.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from waseller.resources.models import Resource
from waseller.resources.repository import ResourceRepositoryPort

# Public kind constants — these strings are part of the data contract with
# the dashboard, so they should NEVER be changed; introducing a new kind
# means picking a new string, not renaming an existing one.
CONTACT_KIND = "contact"
ACTIVITY_KIND = "activity"

# Truncation cap for the activity summary so the JSONB row stays small
# (the full text lives in the buyer_interactions table; this is for a glance).
_SUMMARY_MAX_CHARS = 240


def contact_external_id(from_number: str) -> str:
    """Canonical external_id for a contact, given the WhatsApp ``from`` field.

    The phone is the only stable identifier we get from Meta; we wrap it in a
    ``buyer:`` namespace so the same number could later host a ``call:``
    activity or a ``deal:`` row without colliding."""
    return f"buyer:{from_number}"


def activity_external_id_for_message(message_id: str, *, direction: str) -> str:
    """Per-turn external_id. Inbound uses the Meta ``message_id``; outbound
    doesn't get one from Meta (we're the sender) so we suffix the buyer
    message_id we replied to. The recorder takes care of passing the right
    ``message_id`` per branch."""
    return f"{direction}:{message_id}"


@dataclass(slots=True)
class CrmRecorder:
    """Append-only timeline + contact updates over :class:`ResourceRepositoryPort`."""

    resources: ResourceRepositoryPort

    # ------------------------------------------------------------------
    # Contact upsert (inbound only — outbound never creates a contact)
    # ------------------------------------------------------------------
    def upsert_contact_for_inbound(
        self,
        *,
        tenant_id: str,
        from_number: str,
        profile_name: str | None = None,
        at: datetime | None = None,
    ) -> Resource:
        """Create the contact if it doesn't exist; bump counters + last_seen
        if it does. Returns the persisted contact.

        Idempotent on (tenant_id, ``buyer:<phone>``)."""
        when = at or datetime.now(UTC)
        ext_id = contact_external_id(from_number)
        existing = self.resources.find_by_external_id(tenant_id, CONTACT_KIND, ext_id)

        if existing is None:
            data: dict[str, Any] = {
                "phone": from_number,
                "source": "whatsapp",
                "first_contact_at": when.isoformat(),
                "last_seen_at": when.isoformat(),
                "turn_count": 1,
            }
            if profile_name:
                data["name"] = profile_name
            summary = profile_name or f"+{from_number}"
            return self.resources.add(
                Resource(
                    tenant_id=tenant_id,
                    kind=CONTACT_KIND,
                    external_id=ext_id,
                    data=data,
                    summary=summary[:_SUMMARY_MAX_CHARS],
                )
            )

        # Existing — bump counters + last_seen + (maybe) refresh name.
        new_data = dict(existing.data)
        new_data["last_seen_at"] = when.isoformat()
        new_data["turn_count"] = int(new_data.get("turn_count", 0)) + 1
        if profile_name and not new_data.get("name"):
            new_data["name"] = profile_name
        new_summary = (
            (new_data.get("name") if isinstance(new_data.get("name"), str) else None)
            or existing.summary
            or f"+{from_number}"
        )
        updated = existing.model_copy(
            update={
                "data": new_data,
                "summary": new_summary[:_SUMMARY_MAX_CHARS],
                "updated_at": when,
            }
        )
        return self.resources.upsert(updated)

    # ------------------------------------------------------------------
    # Activity append (one per turn, both directions)
    # ------------------------------------------------------------------
    def record_activity(
        self,
        *,
        tenant_id: str,
        contact_id: str,
        direction: str,
        text: str,
        message_id: str,
        activity_type: str = "whatsapp_message",
        at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Resource:
        """Append one activity to the contact's timeline.

        Idempotent on the (direction, message_id) tuple so Meta webhook
        retries — or our own outbound retries — never duplicate the row."""
        when = at or datetime.now(UTC)
        ext_id = activity_external_id_for_message(message_id, direction=direction)

        existing = self.resources.find_by_external_id(tenant_id, ACTIVITY_KIND, ext_id)
        if existing is not None:
            return existing

        summary = (text or "").strip().replace("\n", " ")
        if len(summary) > _SUMMARY_MAX_CHARS:
            summary = summary[: _SUMMARY_MAX_CHARS - 1].rstrip() + "…"

        data: dict[str, Any] = {
            "contact_id": contact_id,
            "type": activity_type,
            "direction": direction,
            "at": when.isoformat(),
            "text": text,
            "message_id": message_id,
        }
        if extra:
            data.update(extra)

        return self.resources.add(
            Resource(
                tenant_id=tenant_id,
                kind=ACTIVITY_KIND,
                external_id=ext_id,
                data=data,
                summary=summary,
            )
        )

    # ------------------------------------------------------------------
    # Composite helpers — what the webhook handler actually calls
    # ------------------------------------------------------------------
    def record_inbound(
        self,
        *,
        tenant_id: str,
        from_number: str,
        text: str,
        message_id: str,
        profile_name: str | None = None,
        at: datetime | None = None,
    ) -> tuple[Resource, Resource]:
        """Atomic-ish helper: upsert contact + append inbound activity. Two
        separate writes; callers don't get an interleaving guarantee but in
        practice the resource store is single-writer and the (contact,
        activity) pair always lands together."""
        contact = self.upsert_contact_for_inbound(
            tenant_id=tenant_id,
            from_number=from_number,
            profile_name=profile_name,
            at=at,
        )
        activity = self.record_activity(
            tenant_id=tenant_id,
            contact_id=contact.id,
            direction="inbound",
            text=text,
            message_id=message_id,
            at=at,
        )
        return contact, activity

    def record_outbound(
        self,
        *,
        tenant_id: str,
        from_number: str,
        text: str,
        reply_to_message_id: str,
        at: datetime | None = None,
        extra: dict[str, Any] | None = None,
    ) -> Resource | None:
        """Append an outbound activity. Returns ``None`` when the contact
        doesn't exist — the recorder refuses to invent one for outbound;
        outbound replies always follow inbound, so a missing contact means
        the inbound path is broken upstream and we'd rather surface that as
        a silent gap than create orphan timelines."""
        contact = self.resources.find_by_external_id(
            tenant_id, CONTACT_KIND, contact_external_id(from_number)
        )
        if contact is None:
            return None
        return self.record_activity(
            tenant_id=tenant_id,
            contact_id=contact.id,
            direction="outbound",
            text=text,
            message_id=reply_to_message_id,
            at=at,
            extra=extra,
        )
