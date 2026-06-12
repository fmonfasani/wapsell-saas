"""Tests for the billing subsystem (PR #47)."""

from __future__ import annotations

import hashlib
import hmac
import json
from typing import Any

import pytest

from waseller.billing import (
    PLANS,
    BillingConflictError,
    BillingService,
    InMemorySubscriptionRepository,
    MercadoPagoError,
    Subscription,
    SubscriptionStatus,
    get_plan,
)
from waseller.billing.adapter import (
    MercadoPagoAdapter,
    PreapprovalResult,
    verify_mp_webhook_signature,
)

pytestmark = pytest.mark.unit


# --- Plan catalog ---------------------------------------------------------


class TestPlans:
    def test_three_plans_defined(self) -> None:
        assert set(PLANS.keys()) == {"STARTER", "PRO", "ENTERPRISE"}

    def test_price_ars_converts_from_cents(self) -> None:
        starter = get_plan("STARTER")
        assert starter.price_ars == 29_000.0

    def test_unknown_plan_raises_with_valid_list(self) -> None:
        with pytest.raises(KeyError, match="unknown plan code"):
            get_plan("BANANA")


# --- Repository ---------------------------------------------------------


class TestInMemorySubscriptionRepository:
    def test_add_then_get(self) -> None:
        repo = InMemorySubscriptionRepository()
        sub = Subscription(tenant_id="t1", plan_code="PRO")
        repo.add(sub)
        assert repo.get(sub.id) == sub

    def test_get_by_preapproval_id(self) -> None:
        repo = InMemorySubscriptionRepository()
        sub = Subscription(
            tenant_id="t1",
            plan_code="PRO",
            mp_preapproval_id="mp-abc",
        )
        repo.add(sub)
        assert repo.get_by_preapproval_id("mp-abc") == sub
        assert repo.get_by_preapproval_id("nope") is None

    def test_active_for_tenant_only_authorized(self) -> None:
        repo = InMemorySubscriptionRepository()
        repo.add(Subscription(tenant_id="t1", plan_code="PRO", status=SubscriptionStatus.PENDING))
        auth = Subscription(tenant_id="t1", plan_code="PRO", status=SubscriptionStatus.AUTHORIZED)
        repo.add(auth)
        assert repo.active_for_tenant("t1") == auth

    def test_list_for_filters_by_tenant(self) -> None:
        repo = InMemorySubscriptionRepository()
        repo.add(Subscription(tenant_id="t1", plan_code="PRO"))
        repo.add(Subscription(tenant_id="t2", plan_code="STARTER"))
        assert len(repo.list_for("t1")) == 1
        assert len(repo.list_for("t2")) == 1

    def test_update_unknown_raises(self) -> None:
        repo = InMemorySubscriptionRepository()
        unknown = Subscription(tenant_id="t1", plan_code="PRO")
        with pytest.raises(KeyError):
            repo.update(unknown)


# --- BillingService -------------------------------------------------------


class _StubMpAdapter:
    """Test double — captures the create_preapproval call and returns the
    canned result; reconcile_from_webhook tests use a different stub below."""

    def __init__(
        self,
        *,
        result: PreapprovalResult | None = None,
        raises: Exception | None = None,
        get_data: dict[str, Any] | None = None,
    ) -> None:
        self._result = result or PreapprovalResult(
            preapproval_id="mp-test-1",
            init_point="https://mp.test/checkout/abc",
            status="pending",
        )
        self._raises = raises
        self._get_data = get_data or {}
        self.create_calls: list[dict[str, Any]] = []
        self.cancel_calls: list[str] = []

    async def create_preapproval(self, **kwargs: Any) -> PreapprovalResult:
        if self._raises is not None:
            raise self._raises
        self.create_calls.append(kwargs)
        return self._result

    async def get_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        return self._get_data

    async def cancel_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        self.cancel_calls.append(preapproval_id)
        return {"status": "cancelled"}


class TestBillingServiceSubscribe:
    @pytest.mark.asyncio
    async def test_subscribe_creates_pending_row(self) -> None:
        repo = InMemorySubscriptionRepository()
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://wapsell.com/callback",
        )
        result = await service.subscribe(
            tenant_id="t1",
            plan_code="PRO",
            payer_email="buyer@example.com",
        )
        assert result.subscription.tenant_id == "t1"
        assert result.subscription.plan_code == "PRO"
        assert result.subscription.mp_preapproval_id == "mp-test-1"
        assert result.init_point == "https://mp.test/checkout/abc"
        assert adapter.create_calls[0]["payer_email"] == "buyer@example.com"
        assert adapter.create_calls[0]["plan_name"] == "Wapsell Pro"
        # The amount is in pesos (not cents) — MP wants decimal ARS.
        assert adapter.create_calls[0]["amount_ars"] == 99_000.0

    @pytest.mark.asyncio
    async def test_subscribe_passes_external_reference_as_local_id(self) -> None:
        repo = InMemorySubscriptionRepository()
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://wapsell.com/callback",
        )
        result = await service.subscribe(tenant_id="t1", plan_code="STARTER", payer_email="b@x.com")
        assert adapter.create_calls[0]["external_reference"] == result.subscription.id

    @pytest.mark.asyncio
    async def test_subscribe_blocks_when_active_exists(self) -> None:
        repo = InMemorySubscriptionRepository()
        repo.add(
            Subscription(
                tenant_id="t1",
                plan_code="PRO",
                status=SubscriptionStatus.AUTHORIZED,
            )
        )
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://wapsell.com/callback",
        )
        with pytest.raises(BillingConflictError):
            await service.subscribe(tenant_id="t1", plan_code="STARTER", payer_email="b@x.com")

    @pytest.mark.asyncio
    async def test_subscribe_bubbles_mp_errors(self) -> None:
        repo = InMemorySubscriptionRepository()
        adapter = _StubMpAdapter(raises=MercadoPagoError("boom"))
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://wapsell.com/callback",
        )
        with pytest.raises(MercadoPagoError):
            await service.subscribe(tenant_id="t1", plan_code="PRO", payer_email="b@x.com")


class TestBillingServiceReconcile:
    @pytest.mark.asyncio
    async def test_reconcile_flips_to_authorized_and_sets_started_at(self) -> None:
        repo = InMemorySubscriptionRepository()
        sub = Subscription(
            tenant_id="t1",
            plan_code="PRO",
            mp_preapproval_id="mp-1",
            status=SubscriptionStatus.PENDING,
        )
        repo.add(sub)
        adapter = _StubMpAdapter(
            get_data={
                "status": "authorized",
                "next_payment_date": "2026-07-12T10:00:00.000Z",
            }
        )
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://x",
        )
        updated = await service.reconcile_from_webhook(preapproval_id="mp-1")
        assert updated is not None
        assert updated.status == SubscriptionStatus.AUTHORIZED
        assert updated.started_at is not None
        assert updated.current_period_end is not None

    @pytest.mark.asyncio
    async def test_reconcile_unknown_preapproval_returns_none(self) -> None:
        repo = InMemorySubscriptionRepository()
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://x",
        )
        result = await service.reconcile_from_webhook(preapproval_id="ghost")
        assert result is None

    @pytest.mark.asyncio
    async def test_reconcile_unknown_status_keeps_local(self) -> None:
        repo = InMemorySubscriptionRepository()
        sub = Subscription(
            tenant_id="t1",
            plan_code="PRO",
            mp_preapproval_id="mp-1",
            status=SubscriptionStatus.PENDING,
        )
        repo.add(sub)
        adapter = _StubMpAdapter(get_data={"status": "weird_new_state"})
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://x",
        )
        result = await service.reconcile_from_webhook(preapproval_id="mp-1")
        assert result is not None
        # Local state was kept intact.
        assert result.status == SubscriptionStatus.PENDING


class TestBillingServiceCancel:
    @pytest.mark.asyncio
    async def test_cancel_marks_subscription_cancelled(self) -> None:
        repo = InMemorySubscriptionRepository()
        sub = Subscription(
            tenant_id="t1",
            plan_code="PRO",
            mp_preapproval_id="mp-1",
            status=SubscriptionStatus.AUTHORIZED,
        )
        repo.add(sub)
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://x",
        )
        result = await service.cancel(tenant_id="t1", subscription_id=sub.id)
        assert result.status == SubscriptionStatus.CANCELLED
        assert adapter.cancel_calls == ["mp-1"]

    @pytest.mark.asyncio
    async def test_cancel_unknown_subscription_raises(self) -> None:
        repo = InMemorySubscriptionRepository()
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://x",
        )
        with pytest.raises(KeyError):
            await service.cancel(tenant_id="t1", subscription_id="ghost")

    @pytest.mark.asyncio
    async def test_cancel_wrong_tenant_raises(self) -> None:
        repo = InMemorySubscriptionRepository()
        sub = Subscription(tenant_id="t1", plan_code="PRO")
        repo.add(sub)
        adapter = _StubMpAdapter()
        service = BillingService(
            repository=repo,
            mp_adapter=adapter,  # type: ignore[arg-type]
            back_url="https://x",
        )
        with pytest.raises(KeyError):
            await service.cancel(tenant_id="evil", subscription_id=sub.id)


# --- Webhook signature ----------------------------------------------------


class TestVerifyMpWebhookSignature:
    def test_missing_secret_passes_through(self) -> None:
        # Operator hasn't configured MP_WEBHOOK_SECRET yet — we allow the
        # webhook through so the system isn't dead-in-the-water on day one.
        ok = verify_mp_webhook_signature(
            secret="",
            body=b"{}",
            signature_header="ts=1,v1=deadbeef",
            request_id_header="req-1",
            data_id="123",
        )
        assert ok is True

    def test_valid_signature(self) -> None:
        secret = "shh"
        canonical = "id:123;request-id:req-1;ts:1700000000;"
        good = hmac.new(secret.encode(), canonical.encode(), hashlib.sha256).hexdigest()
        ok = verify_mp_webhook_signature(
            secret=secret,
            body=b"{}",
            signature_header=f"ts=1700000000,v1={good}",
            request_id_header="req-1",
            data_id="123",
        )
        assert ok is True

    def test_tampered_payload_rejected(self) -> None:
        ok = verify_mp_webhook_signature(
            secret="shh",
            body=b"{}",
            signature_header="ts=1700000000,v1=deadbeef",
            request_id_header="req-1",
            data_id="123",
        )
        assert ok is False

    def test_missing_v1_rejected(self) -> None:
        ok = verify_mp_webhook_signature(
            secret="shh",
            body=b"{}",
            signature_header="ts=1700000000",
            request_id_header="req-1",
            data_id="123",
        )
        assert ok is False


# --- Adapter HTTP errors --------------------------------------------------


class TestAdapterErrors:
    def test_empty_access_token_rejected(self) -> None:
        with pytest.raises(MercadoPagoError):
            MercadoPagoAdapter(access_token="")


# --- Plan catalog endpoint shape -----------------------------------------


class TestListPlans:
    def test_list_plans_returns_serializable_dicts(self) -> None:
        plans = BillingService.list_plans()
        # Catch any non-JSON-serializable additions (datetimes, custom
        # objects). We pay the small cost so the API layer can blindly
        # forward this without a serializer hook.
        json.dumps(plans)
        assert {p["code"] for p in plans} == {"STARTER", "PRO", "ENTERPRISE"}
