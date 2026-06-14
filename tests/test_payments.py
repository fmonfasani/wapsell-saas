"""Tests for the payments (marketplace split) subsystem — Phase 1 (MP)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

from wapsell.events.bus import InMemoryEventBus
from wapsell.payments import (
    Commission,
    ConnectionStatus,
    LinkStatus,
    MerchantConnection,
    Payment,
    PaymentLink,
    PaymentProvider,
    PaymentSnapshot,
    PaymentStatus,
    PaymentsConflictError,
    PaymentsService,
    WebhookEvent,
)
from wapsell.payments.providers import MercadoPagoMarketplaceAdapter, MercadoPagoSplitError
from wapsell.payments.repository import (
    InMemoryCommissionRepository,
    InMemoryMerchantConnectionRepository,
    InMemoryPaymentLinkRepository,
    InMemoryPaymentRepository,
)
from wapsell.security.crypto import TokenCipher, generate_key

pytestmark = pytest.mark.unit


def _cipher() -> TokenCipher:
    return TokenCipher(base64.urlsafe_b64decode(generate_key()))


# --- Models ---------------------------------------------------------------


class TestModels:
    def test_link_fee_amount_is_basis_points_of_amount(self) -> None:
        link = PaymentLink(
            tenant_id="t1",
            connection_id="c1",
            provider=PaymentProvider.MERCADO_PAGO,
            amount=100_000,  # 1000.00
            currency="ARS",
            fee_bps=500,  # 5%
        )
        assert link.fee_amount == 5_000  # 50.00

    def test_link_fee_rounds_to_nearest_cent(self) -> None:
        link = PaymentLink(
            tenant_id="t1",
            connection_id="c1",
            provider=PaymentProvider.MERCADO_PAGO,
            amount=333,
            currency="ARS",
            fee_bps=500,
        )
        # 333 * 500 / 10000 = 16.65 → 17
        assert link.fee_amount == 17


# --- Repositories ---------------------------------------------------------


class TestRepositories:
    def test_active_connection_filters_status_and_provider(self) -> None:
        repo = InMemoryMerchantConnectionRepository()
        repo.add(
            MerchantConnection(
                tenant_id="t1",
                provider=PaymentProvider.MERCADO_PAGO,
                status=ConnectionStatus.PENDING,
            )
        )
        active = MerchantConnection(
            tenant_id="t1",
            provider=PaymentProvider.MERCADO_PAGO,
            status=ConnectionStatus.ACTIVE,
        )
        repo.add(active)
        assert repo.active_for("t1", PaymentProvider.MERCADO_PAGO) == active
        assert repo.active_for("t1", PaymentProvider.STRIPE) is None

    def test_link_lookup_by_reference(self) -> None:
        repo = InMemoryPaymentLinkRepository()
        link = PaymentLink(
            tenant_id="t1",
            connection_id="c1",
            provider=PaymentProvider.MERCADO_PAGO,
            amount=1000,
            currency="ARS",
            fee_bps=500,
            external_reference="ref-xyz",
        )
        repo.add(link)
        assert repo.get_by_reference("ref-xyz") == link
        assert repo.get_by_reference("nope") is None

    def test_payment_lookup_by_provider_id(self) -> None:
        repo = InMemoryPaymentRepository()
        pay = Payment(
            link_id="l1",
            tenant_id="t1",
            provider=PaymentProvider.MERCADO_PAGO,
            provider_payment_id="mp-pay-1",
            amount=1000,
            currency="ARS",
            status=PaymentStatus.APPROVED,
        )
        repo.add(pay)
        assert repo.get_by_provider_id("mp-pay-1") == pay
        assert repo.get_by_provider_id("ghost") is None


# --- Fake provider (for service tests) ------------------------------------


class _FakeProvider:
    """Implements PaymentProviderPort just enough for the service tests."""

    name = "mercadopago"

    def __init__(self, *, snapshot: PaymentSnapshot | None = None) -> None:
        self._snapshot = snapshot
        self.created: list[dict[str, Any]] = []

    async def start_merchant_onboarding(self, **kwargs: Any) -> Any:
        from wapsell.payments.port import OnboardingLink

        return OnboardingLink(url="https://mp/auth?x", state=kwargs["state"])

    async def complete_merchant_onboarding(
        self, *, tenant_id: str, callback_params: Any
    ) -> MerchantConnection:
        return MerchantConnection(
            tenant_id=tenant_id,
            provider=PaymentProvider.MERCADO_PAGO,
            status=ConnectionStatus.ACTIVE,
            provider_account_id="seller-1",
            access_token_encrypted="enc",
        )

    async def create_payment_link(self, **kwargs: Any) -> Any:
        from wapsell.payments.port import CreatedLink

        self.created.append(kwargs)
        return CreatedLink(url="https://mp/checkout/abc", provider_ref="pref-1")

    async def fetch_payment(
        self, *, connection: MerchantConnection, provider_payment_id: str
    ) -> PaymentSnapshot:
        assert self._snapshot is not None
        return self._snapshot


def _service(provider: _FakeProvider, bus: InMemoryEventBus) -> tuple[PaymentsService, Any]:
    connections = InMemoryMerchantConnectionRepository()
    service = PaymentsService(
        provider=provider,  # type: ignore[arg-type]
        connections=connections,
        links=InMemoryPaymentLinkRepository(),
        payments=InMemoryPaymentRepository(),
        commissions=InMemoryCommissionRepository(),
        event_bus=bus,
    )
    return service, connections


# --- Service: create_link -------------------------------------------------


class TestCreateLink:
    @pytest.mark.asyncio
    async def test_create_link_persists_with_provider_ref_and_default_fee(self) -> None:
        provider = _FakeProvider()
        bus = InMemoryEventBus()
        service, connections = _service(provider, bus)
        connections.add(
            MerchantConnection(
                tenant_id="t1",
                provider=PaymentProvider.MERCADO_PAGO,
                status=ConnectionStatus.ACTIVE,
                access_token_encrypted="enc",
            )
        )
        result = await service.create_link(
            tenant_id="t1", amount=100_000, currency="ARS", description="Reserva"
        )
        assert result.url == "https://mp/checkout/abc"
        assert result.link.provider_ref == "pref-1"
        assert result.link.fee_bps == 500  # default 5%
        assert result.link.status == LinkStatus.OPEN
        # The external_reference is round-tripped to the provider.
        assert provider.created[0]["external_reference"] == result.link.external_reference

    @pytest.mark.asyncio
    async def test_create_link_without_connection_raises(self) -> None:
        provider = _FakeProvider()
        service, _ = _service(provider, InMemoryEventBus())
        with pytest.raises(PaymentsConflictError, match="no active"):
            await service.create_link(tenant_id="t1", amount=1000, currency="ARS")

    @pytest.mark.asyncio
    async def test_create_link_rejects_non_positive_amount(self) -> None:
        provider = _FakeProvider()
        service, _ = _service(provider, InMemoryEventBus())
        with pytest.raises(PaymentsConflictError, match="positive"):
            await service.create_link(tenant_id="t1", amount=0, currency="ARS")


# --- Service: webhook reconciliation --------------------------------------


class TestReconcile:
    @pytest.mark.asyncio
    async def test_approved_payment_records_commission_and_emits_event(self) -> None:
        snapshot = PaymentSnapshot(
            provider_payment_id="mp-pay-1",
            status=PaymentStatus.APPROVED,
            amount=100_000,
            currency="ARS",
            external_reference="ref-1",
        )
        provider = _FakeProvider(snapshot=snapshot)
        bus = InMemoryEventBus()
        service, connections = _service(provider, bus)
        conn = connections.add(
            MerchantConnection(
                tenant_id="t1",
                provider=PaymentProvider.MERCADO_PAGO,
                status=ConnectionStatus.ACTIVE,
                access_token_encrypted="enc",
            )
        )
        created = await service.create_link(
            tenant_id="t1", amount=100_000, currency="ARS", contact_id="buyer-1"
        )
        ext = created.link.external_reference

        payment = await service.reconcile_from_webhook(
            WebhookEvent(provider_payment_id="mp-pay-1", external_reference=ext)
        )
        assert payment is not None
        assert payment.status == PaymentStatus.APPROVED

        events = bus.by_type("payment.completed")
        assert len(events) == 1
        assert events[0].payload["tenant_id"] == "t1"
        assert events[0].payload["fee_amount"] == 5_000  # 5% of 100_000
        assert events[0].payload["amount"] == 100_000
        assert conn.id == created.link.connection_id

    @pytest.mark.asyncio
    async def test_reconcile_is_idempotent(self) -> None:
        snapshot = PaymentSnapshot(
            provider_payment_id="mp-pay-1",
            status=PaymentStatus.APPROVED,
            amount=100_000,
            currency="ARS",
        )
        provider = _FakeProvider(snapshot=snapshot)
        bus = InMemoryEventBus()
        service, connections = _service(provider, bus)
        connections.add(
            MerchantConnection(
                tenant_id="t1",
                provider=PaymentProvider.MERCADO_PAGO,
                status=ConnectionStatus.ACTIVE,
                access_token_encrypted="enc",
            )
        )
        created = await service.create_link(tenant_id="t1", amount=100_000, currency="ARS")
        evt = WebhookEvent(
            provider_payment_id="mp-pay-1", external_reference=created.link.external_reference
        )
        first = await service.reconcile_from_webhook(evt)
        second = await service.reconcile_from_webhook(evt)
        assert first is not None
        assert second is None  # already processed
        assert len(bus.by_type("payment.completed")) == 1

    @pytest.mark.asyncio
    async def test_unknown_reference_returns_none(self) -> None:
        provider = _FakeProvider()
        service, _ = _service(provider, InMemoryEventBus())
        result = await service.reconcile_from_webhook(
            WebhookEvent(provider_payment_id="x", external_reference="ghost")
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_non_approved_payment_leaves_link_open(self) -> None:
        snapshot = PaymentSnapshot(
            provider_payment_id="mp-pay-1",
            status=PaymentStatus.PENDING,
            amount=100_000,
            currency="ARS",
        )
        provider = _FakeProvider(snapshot=snapshot)
        bus = InMemoryEventBus()
        service, connections = _service(provider, bus)
        connections.add(
            MerchantConnection(
                tenant_id="t1",
                provider=PaymentProvider.MERCADO_PAGO,
                status=ConnectionStatus.ACTIVE,
                access_token_encrypted="enc",
            )
        )
        created = await service.create_link(tenant_id="t1", amount=100_000, currency="ARS")
        result = await service.reconcile_from_webhook(
            WebhookEvent(
                provider_payment_id="mp-pay-1",
                external_reference=created.link.external_reference,
            )
        )
        assert result is None
        assert not bus.by_type("payment.completed")


# --- MP adapter -----------------------------------------------------------


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = json.dumps(payload)

    def json(self) -> dict[str, Any]:
        return self._payload


class _FakeHttpClient:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self._status = status_code
        self.requests: list[dict[str, Any]] = []

    async def request(self, method: str, url: str, **kwargs: Any) -> _FakeResponse:
        self.requests.append({"method": method, "url": url, **kwargs})
        return _FakeResponse(self._status, self._payload)

    async def aclose(self) -> None:  # pragma: no cover — not called (client injected)
        pass


def _adapter(client: _FakeHttpClient | None = None, *, webhook_secret: str = "") -> MercadoPagoMarketplaceAdapter:
    return MercadoPagoMarketplaceAdapter(
        client_id="app-id",
        client_secret="app-secret",
        redirect_uri="https://app.wapsell.com/payments/mp/callback",
        webhook_base_url="https://api.wapsell.com",
        cipher=_cipher(),
        webhook_secret=webhook_secret,
        client=client,  # type: ignore[arg-type]
    )


class TestMpAdapterOnboarding:
    @pytest.mark.asyncio
    async def test_onboarding_url_carries_client_id_and_state(self) -> None:
        adapter = _adapter()
        link = await adapter.start_merchant_onboarding(
            tenant_id="t1", return_url="https://x", state="st-123"
        )
        assert "client_id=app-id" in link.url
        assert "state=st-123" in link.url
        assert link.url.startswith("https://auth.mercadopago.com/authorization")

    @pytest.mark.asyncio
    async def test_complete_onboarding_encrypts_token(self) -> None:
        client = _FakeHttpClient({"access_token": "SELLER-TOKEN", "user_id": 42})
        adapter = _adapter(client)
        conn = await adapter.complete_merchant_onboarding(
            tenant_id="t1", callback_params={"code": "auth-code"}
        )
        assert conn.status == ConnectionStatus.ACTIVE
        assert conn.provider_account_id == "42"
        # Token is stored encrypted, never plaintext.
        assert conn.access_token_encrypted is not None
        assert conn.access_token_encrypted != "SELLER-TOKEN"

    @pytest.mark.asyncio
    async def test_complete_onboarding_without_code_raises(self) -> None:
        adapter = _adapter(_FakeHttpClient({}))
        with pytest.raises(MercadoPagoSplitError, match="code"):
            await adapter.complete_merchant_onboarding(tenant_id="t1", callback_params={})


class TestMpAdapterCreateLink:
    @pytest.mark.asyncio
    async def test_payload_includes_marketplace_fee_and_notification_ref(self) -> None:
        client = _FakeHttpClient({"id": "pref-1", "init_point": "https://mp/checkout/x"})
        adapter = _adapter(client)
        cipher = adapter._cipher  # reuse same cipher to forge a token
        conn = MerchantConnection(
            tenant_id="t1",
            provider=PaymentProvider.MERCADO_PAGO,
            status=ConnectionStatus.ACTIVE,
            access_token_encrypted=cipher.encrypt("SELLER-TOKEN"),
        )
        result = await adapter.create_payment_link(
            connection=conn,
            amount=100_000,  # 1000.00
            currency="ARS",
            fee_bps=500,
            external_reference="ref-1",
            description="Reserva",
        )
        assert result.provider_ref == "pref-1"
        assert result.url == "https://mp/checkout/x"
        body = client.requests[0]["json"]
        assert body["marketplace_fee"] == 50.0  # 5% of 1000.00
        assert body["items"][0]["unit_price"] == 1000.0
        assert "ref=ref-1" in body["notification_url"]
        # Seller token is used (not the platform).
        assert client.requests[0]["headers"]["Authorization"] == "Bearer SELLER-TOKEN"


class TestMpAdapterWebhook:
    def test_verify_webhook_payment_topic_passthrough_without_secret(self) -> None:
        adapter = _adapter()  # no secret → signature skipped
        evt = adapter.verify_webhook(
            body=b"{}",
            headers={},
            query={"topic": "payment", "id": "mp-pay-1", "ref": "ref-1"},
        )
        assert evt is not None
        assert evt.provider_payment_id == "mp-pay-1"
        assert evt.external_reference == "ref-1"

    def test_verify_webhook_ignores_non_payment_topic(self) -> None:
        adapter = _adapter()
        evt = adapter.verify_webhook(
            body=b"{}", headers={}, query={"topic": "merchant_order", "id": "x"}
        )
        assert evt is None

    def test_verify_webhook_drops_when_no_id(self) -> None:
        adapter = _adapter()
        evt = adapter.verify_webhook(body=b"{}", headers={}, query={"topic": "payment"})
        assert evt is None


class TestMpAdapterFetch:
    @pytest.mark.asyncio
    async def test_fetch_payment_maps_approved_status_and_amount(self) -> None:
        client = _FakeHttpClient(
            {
                "status": "approved",
                "transaction_amount": 1000.0,
                "currency_id": "ARS",
                "external_reference": "ref-1",
                "date_approved": "2026-06-14T10:00:00.000Z",
            }
        )
        adapter = _adapter(client)
        cipher = adapter._cipher
        conn = MerchantConnection(
            tenant_id="t1",
            provider=PaymentProvider.MERCADO_PAGO,
            status=ConnectionStatus.ACTIVE,
            access_token_encrypted=cipher.encrypt("SELLER-TOKEN"),
        )
        snap = await adapter.fetch_payment(connection=conn, provider_payment_id="mp-pay-1")
        assert snap.status == PaymentStatus.APPROVED
        assert snap.amount == 100_000  # 1000.00 → cents
        assert snap.currency == "ARS"
        assert snap.external_reference == "ref-1"
        assert snap.paid_at is not None