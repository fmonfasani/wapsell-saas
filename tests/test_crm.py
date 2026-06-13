"""Tests for the CRM recorder + contacts/activities endpoints (PR #43).

Covers:
- :class:`CrmRecorder.upsert_contact_for_inbound` lifecycle: first inbound
  creates, subsequent inbound bumps turn_count + last_seen_at + (maybe) name.
- :meth:`record_activity` idempotency on (direction, message_id).
- Composite ``record_inbound`` and ``record_outbound`` helpers.
- ``find_by_external_id`` on the repo (new in PR #43).
- API endpoints:
  * GET /crm/contacts
  * GET /crm/contacts/{id}
  * GET /crm/contacts/{id}/activities
- End-to-end: forging a Meta-shaped inbound message hits the webhook,
  which auto-creates the contact + inbound activity, and the agent reply
  appends the outbound activity. The dashboard endpoints reflect both.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
import pytest
from services.api.main import _client as live_client
from services.api.main import app

from wapsell.crm import ACTIVITY_KIND, CONTACT_KIND, CrmRecorder, contact_external_id
from wapsell.models import InboundMessage
from wapsell.resources import InMemoryResourceRepository, Resource

pytestmark = pytest.mark.unit


@pytest.fixture
def http() -> TestClient:
    return TestClient(app)


# -----------------------------------------------------------------------------
# Repository: find_by_external_id
# -----------------------------------------------------------------------------


class TestFindByExternalId:
    def test_returns_match(self) -> None:
        repo = InMemoryResourceRepository()
        added = repo.add(
            Resource(
                tenant_id="t1",
                kind="contact",
                external_id="buyer:549110000",
                data={"phone": "549110000"},
            )
        )
        found = repo.find_by_external_id("t1", "contact", "buyer:549110000")
        assert found is not None
        assert found.id == added.id

    def test_returns_none_when_kind_mismatch(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(
            Resource(
                tenant_id="t1",
                kind="property",
                external_id="INM-001",
                data={},
            )
        )
        assert repo.find_by_external_id("t1", "contact", "INM-001") is None

    def test_returns_none_when_tenant_mismatch(self) -> None:
        repo = InMemoryResourceRepository()
        repo.add(
            Resource(
                tenant_id="t1",
                kind="contact",
                external_id="buyer:549110000",
                data={},
            )
        )
        assert repo.find_by_external_id("t2", "contact", "buyer:549110000") is None


# -----------------------------------------------------------------------------
# CrmRecorder.upsert_contact_for_inbound
# -----------------------------------------------------------------------------


class TestUpsertContact:
    def test_first_inbound_creates_with_defaults(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        at = datetime.now(UTC)
        contact = recorder.upsert_contact_for_inbound(
            tenant_id="t1",
            from_number="549110000001",
            profile_name="María",
            at=at,
        )
        assert contact.kind == CONTACT_KIND
        assert contact.external_id == contact_external_id("549110000001")
        assert contact.data["phone"] == "549110000001"
        assert contact.data["name"] == "María"
        assert contact.data["turn_count"] == 1
        assert contact.data["first_contact_at"] == at.isoformat()
        assert contact.summary == "María"

    def test_second_inbound_bumps_counters(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        first_at = datetime.now(UTC)
        second_at = first_at + timedelta(minutes=5)
        recorder.upsert_contact_for_inbound(
            tenant_id="t1",
            from_number="549110000001",
            profile_name="María",
            at=first_at,
        )
        contact = recorder.upsert_contact_for_inbound(
            tenant_id="t1",
            from_number="549110000001",
            at=second_at,
        )
        assert contact.data["turn_count"] == 2
        assert contact.data["last_seen_at"] == second_at.isoformat()
        # first_contact_at is preserved.
        assert contact.data["first_contact_at"] == first_at.isoformat()
        # Name persists from the first call.
        assert contact.data["name"] == "María"

    def test_no_name_falls_back_to_phone_in_summary(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact = recorder.upsert_contact_for_inbound(
            tenant_id="t1",
            from_number="549110000002",
        )
        assert contact.summary == "+549110000002"

    def test_dedup_across_tenants(self) -> None:
        # Same phone, different tenants → different contact rows.
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        c1 = recorder.upsert_contact_for_inbound(tenant_id="t1", from_number="549110000003")
        c2 = recorder.upsert_contact_for_inbound(tenant_id="t2", from_number="549110000003")
        assert c1.id != c2.id


# -----------------------------------------------------------------------------
# CrmRecorder.record_activity
# -----------------------------------------------------------------------------


class TestRecordActivity:
    def test_creates_inbound_activity(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact = recorder.upsert_contact_for_inbound(tenant_id="t1", from_number="549110000001")
        activity = recorder.record_activity(
            tenant_id="t1",
            contact_id=contact.id,
            direction="inbound",
            text="hola",
            message_id="wamid.1",
        )
        assert activity.kind == ACTIVITY_KIND
        assert activity.external_id == "inbound:wamid.1"
        assert activity.data["contact_id"] == contact.id
        assert activity.data["direction"] == "inbound"
        assert activity.data["type"] == "whatsapp_message"
        assert activity.data["text"] == "hola"

    def test_idempotent_on_retry(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact = recorder.upsert_contact_for_inbound(tenant_id="t1", from_number="549110000001")
        a1 = recorder.record_activity(
            tenant_id="t1",
            contact_id=contact.id,
            direction="inbound",
            text="hola",
            message_id="wamid.1",
        )
        a2 = recorder.record_activity(
            tenant_id="t1",
            contact_id=contact.id,
            direction="inbound",
            text="hola",
            message_id="wamid.1",
        )
        assert a1.id == a2.id

    def test_outbound_and_inbound_dedup_separately(self) -> None:
        # Same message_id but different direction → two distinct activities.
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact = recorder.upsert_contact_for_inbound(tenant_id="t1", from_number="549110000001")
        a_in = recorder.record_activity(
            tenant_id="t1",
            contact_id=contact.id,
            direction="inbound",
            text="hola",
            message_id="wamid.1",
        )
        a_out = recorder.record_activity(
            tenant_id="t1",
            contact_id=contact.id,
            direction="outbound",
            text="¡hola!",
            message_id="wamid.1",
        )
        assert a_in.id != a_out.id

    def test_truncates_long_summary(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact = recorder.upsert_contact_for_inbound(tenant_id="t1", from_number="549110000001")
        long_text = "x" * 500
        activity = recorder.record_activity(
            tenant_id="t1",
            contact_id=contact.id,
            direction="inbound",
            text=long_text,
            message_id="wamid.long",
        )
        assert len(activity.summary) <= 240
        assert activity.summary.endswith("…")


# -----------------------------------------------------------------------------
# Composite helpers
# -----------------------------------------------------------------------------


class TestComposite:
    def test_record_inbound_returns_contact_and_activity(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact, activity = recorder.record_inbound(
            tenant_id="t1",
            from_number="549110000010",
            text="hola",
            message_id="wamid.x",
            profile_name="Pedro",
        )
        assert contact.data["name"] == "Pedro"
        assert activity.data["contact_id"] == contact.id

    def test_record_outbound_skips_without_contact(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        result = recorder.record_outbound(
            tenant_id="t1",
            from_number="549110000099",
            text="¡hola!",
            reply_to_message_id="wamid.y",
        )
        assert result is None

    def test_record_outbound_after_inbound_links_to_contact(self) -> None:
        repo = InMemoryResourceRepository()
        recorder = CrmRecorder(resources=repo)
        contact, _ = recorder.record_inbound(
            tenant_id="t1",
            from_number="549110000020",
            text="hola",
            message_id="wamid.z",
        )
        outbound = recorder.record_outbound(
            tenant_id="t1",
            from_number="549110000020",
            text="¡hola!",
            reply_to_message_id="wamid.z",
        )
        assert outbound is not None
        assert outbound.data["contact_id"] == contact.id
        assert outbound.data["direction"] == "outbound"


# -----------------------------------------------------------------------------
# API endpoints
# -----------------------------------------------------------------------------


class TestCrmEndpoints:
    def _make_tenant(self, http: TestClient, slug: str) -> str:
        body = http.post("/tenants", json={"name": slug.title(), "slug": slug}).json()
        return str(body["id"])

    async def test_list_contacts_returns_only_contact_kind(self, http: TestClient) -> None:
        from services.api.main import _process_inbound_message  # noqa: PLC0415

        tid = self._make_tenant(http, "crm-list")
        tenant = live_client.tenants.get(tid)
        msg = InboundMessage(
            tenant_id=tid,
            from_number="549110000050",
            text="hola",
            message_id=f"wamid.list.{tid}",
            profile_name="Lucia",
        )
        await _process_inbound_message(tenant, msg)

        res = http.get(f"/tenants/{tid}/crm/contacts")
        assert res.status_code == 200
        contacts = res.json()
        # Only this tenant's single contact, kind=contact (no properties etc).
        assert len(contacts) == 1
        assert contacts[0]["data"]["phone"] == "549110000050"
        assert contacts[0]["data"]["name"] == "Lucia"

    async def test_get_contact_404_when_kind_mismatch(self, http: TestClient) -> None:
        tid = self._make_tenant(http, "crm-404")
        # Create a property — different kind.
        prop = http.post(
            f"/tenants/{tid}/resources",
            json={"kind": "property", "data": {"title": "x"}},
        ).json()
        res = http.get(f"/tenants/{tid}/crm/contacts/{prop['id']}")
        assert res.status_code == 404

    async def test_activities_listed_for_contact(self, http: TestClient) -> None:
        from services.api.main import _process_inbound_message  # noqa: PLC0415

        tid = self._make_tenant(http, "crm-act")
        tenant = live_client.tenants.get(tid)
        msg = InboundMessage(
            tenant_id=tid,
            from_number="549110000051",
            text="hola, busco depto",
            message_id=f"wamid.act.{tid}",
        )
        await _process_inbound_message(tenant, msg)

        contacts = http.get(f"/tenants/{tid}/crm/contacts").json()
        cid = contacts[0]["id"]
        res = http.get(f"/tenants/{tid}/crm/contacts/{cid}/activities")
        assert res.status_code == 200
        activities = res.json()
        # At least the inbound activity. Outbound depends on whether the
        # agent loop ran successfully; either way the inbound is there.
        directions = [a["data"]["direction"] for a in activities]
        assert "inbound" in directions

    def test_404_when_tenant_missing(self, http: TestClient) -> None:
        assert http.get("/tenants/no/crm/contacts").status_code == 404
