"""MercadoPagoMarketplaceAdapter — split payments via OAuth + Checkout Pro.

This is the *marketplace* flow, distinct from ``billing/adapter.py`` which uses
the Preapproval API for recurring SaaS subscriptions. Here:

1. The seller authorizes Wapsell once via OAuth (``start_merchant_onboarding`` →
   ``complete_merchant_onboarding``). We store their access token, encrypted.
2. On each sale we create a Checkout Pro *preference* using the **seller's**
   token with a ``marketplace_fee`` — MP credits the seller and retains our cut
   into Wapsell's collector account automatically (``create_payment_link``).
3. MP fires a ``topic=payment`` webhook; we verify the signature, then read the
   payment back with the seller's token to reconcile (``fetch_payment``).

We round-trip the link's ``external_reference`` by appending it to the
per-preference ``notification_url`` (``?ref=...``) so the webhook can find the
local row before fetching — MP's notification body carries only the payment id.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import json
import logging
from typing import Any
from urllib.parse import urlencode

import httpx

from wapsell.billing.adapter import verify_mp_webhook_signature
from wapsell.payments.models import (
    ConnectionStatus,
    MerchantConnection,
    PaymentProvider,
    PaymentStatus,
)
from wapsell.payments.port import (
    CreatedLink,
    OnboardingLink,
    PaymentSnapshot,
    WebhookEvent,
)
from wapsell.security.crypto import TokenCipher

_log = logging.getLogger("wapsell.payments.mercadopago")

_MP_API = "https://api.mercadopago.com"
_MP_AUTH = "https://auth.mercadopago.com/authorization"
_HTTP_ERROR_THRESHOLD = 400

# MP payment status → our normalized PaymentStatus. Anything unmapped stays
# PENDING so reconcile is a safe no-op instead of a wrong terminal flip.
_STATUS_MAP: dict[str, PaymentStatus] = {
    "approved": PaymentStatus.APPROVED,
    "authorized": PaymentStatus.APPROVED,
    "refunded": PaymentStatus.REFUNDED,
    "charged_back": PaymentStatus.REFUNDED,
    "cancelled": PaymentStatus.REJECTED,
    "rejected": PaymentStatus.REJECTED,
    "pending": PaymentStatus.PENDING,
    "in_process": PaymentStatus.PENDING,
}


class MercadoPagoSplitError(RuntimeError):
    """Wraps any error from the MP marketplace API at the boundary."""


class MercadoPagoMarketplaceAdapter:
    """Production MP marketplace client.

    ``client_id`` / ``client_secret`` come from your **Marketplace** application
    (developers.mercadopago.com → your app), not the Preapproval app. The
    ``cipher`` encrypts/decrypts the per-seller OAuth token at the boundary so
    the service never touches plaintext credentials.
    """

    name = "mercadopago"

    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        webhook_base_url: str,
        cipher: TokenCipher,
        webhook_secret: str = "",
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not (client_id and client_secret):
            raise MercadoPagoSplitError("client_id and client_secret are required")
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._webhook_base = webhook_base_url.rstrip("/")
        self._cipher = cipher
        self._webhook_secret = webhook_secret
        self._client = client
        self._timeout = timeout

    # ------------------------------------------------------------------
    # Onboarding (OAuth)
    # ------------------------------------------------------------------
    async def start_merchant_onboarding(
        self, *, tenant_id: str, return_url: str, state: str
    ) -> OnboardingLink:
        # ``state`` carries our CSRF/correlation token; ``return_url`` is unused
        # by MP (the redirect_uri is fixed on the app) but kept for port parity.
        params = {
            "client_id": self._client_id,
            "response_type": "code",
            "platform_id": "mp",
            "redirect_uri": self._redirect_uri,
            "state": state,
        }
        return OnboardingLink(url=f"{_MP_AUTH}?{urlencode(params)}", state=state)

    async def complete_merchant_onboarding(
        self, *, tenant_id: str, callback_params: Mapping[str, str]
    ) -> MerchantConnection:
        code = callback_params.get("code")
        if not code:
            raise MercadoPagoSplitError("missing 'code' in OAuth callback")
        payload = {
            "client_id": self._client_id,
            "client_secret": self._client_secret,
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": self._redirect_uri,
        }
        data = await self._post("/oauth/token", payload, token=None)
        access = data.get("access_token")
        if not access:
            raise MercadoPagoSplitError("OAuth token exchange returned no access_token")
        refresh = data.get("refresh_token")
        return MerchantConnection(
            tenant_id=tenant_id,
            provider=PaymentProvider.MERCADO_PAGO,
            status=ConnectionStatus.ACTIVE,
            provider_account_id=str(data.get("user_id")) if data.get("user_id") else None,
            access_token_encrypted=self._cipher.encrypt(str(access)),
            refresh_token_encrypted=self._cipher.encrypt(str(refresh)) if refresh else None,
        )

    # ------------------------------------------------------------------
    # Create link (Checkout Pro preference with marketplace_fee)
    # ------------------------------------------------------------------
    async def create_payment_link(
        self,
        *,
        connection: MerchantConnection,
        amount: int,
        currency: str,
        fee_bps: int,
        external_reference: str,
        description: str,
    ) -> CreatedLink:
        token = self._seller_token(connection)
        # ``notification_url`` carries the external_reference so the webhook can
        # locate the local link before fetching the payment from MP.
        notify = f"{self._webhook_base}/payments/mp/webhook?ref={external_reference}"
        payload: dict[str, Any] = {
            "items": [
                {
                    "title": description or "Compra",
                    "quantity": 1,
                    "unit_price": amount / 100,
                    "currency_id": currency,
                }
            ],
            "marketplace_fee": round(amount * fee_bps / 10_000) / 100,
            "external_reference": external_reference,
            "notification_url": notify,
        }
        data = await self._post("/checkout/preferences", payload, token=token)
        init_point = data.get("init_point") or data.get("sandbox_init_point") or ""
        return CreatedLink(
            url=str(init_point),
            provider_ref=str(data.get("id", "")),
            raw_status="created",
        )

    # ------------------------------------------------------------------
    # Webhook
    # ------------------------------------------------------------------
    def verify_webhook(
        self, *, body: bytes, headers: Mapping[str, str], query: Mapping[str, str]
    ) -> WebhookEvent | None:
        topic = query.get("topic") or query.get("type") or ""
        data_id = query.get("id") or query.get("data.id") or ""
        if not data_id:
            # Body form: {"type":"payment","data":{"id":"..."}}.
            parsed = _safe_json(body)
            topic = topic or str(parsed.get("type", ""))
            data_id = str((parsed.get("data") or {}).get("id", ""))
        if topic and topic != "payment":
            # We only act on payment notifications; merchant_order etc. are
            # acknowledged and dropped.
            return None
        if not data_id:
            return None

        ok = verify_mp_webhook_signature(
            self._webhook_secret,
            body,
            headers.get("x-signature", ""),
            headers.get("x-request-id", ""),
            str(data_id),
        )
        if not ok:
            _log.warning("MP split webhook signature failed for payment %s", data_id)
            return None

        return WebhookEvent(
            provider_payment_id=str(data_id),
            external_reference=query.get("ref"),
            kind="payment",
        )

    async def fetch_payment(
        self, *, connection: MerchantConnection, provider_payment_id: str
    ) -> PaymentSnapshot:
        token = self._seller_token(connection)
        data = await self._get(f"/v1/payments/{provider_payment_id}", token=token)
        status = _STATUS_MAP.get(str(data.get("status", "")).lower(), PaymentStatus.PENDING)
        amount = round(float(data.get("transaction_amount") or 0) * 100)
        approved_raw = data.get("date_approved")
        paid_at: datetime | None = None
        if isinstance(approved_raw, str) and approved_raw:
            try:
                paid_at = datetime.fromisoformat(approved_raw.replace("Z", "+00:00"))
            except ValueError:
                paid_at = None
        return PaymentSnapshot(
            provider_payment_id=str(provider_payment_id),
            status=status,
            amount=amount,
            currency=str(data.get("currency_id", "")),
            external_reference=data.get("external_reference"),
            paid_at=paid_at,
        )

    # ------------------------------------------------------------------
    # internals
    # ------------------------------------------------------------------
    def _seller_token(self, connection: MerchantConnection) -> str:
        if not connection.access_token_encrypted:
            raise MercadoPagoSplitError(
                f"connection {connection.id} has no MP access token"
            )
        return self._cipher.decrypt(connection.access_token_encrypted)

    async def _post(
        self, path: str, body: dict[str, Any], *, token: str | None
    ) -> dict[str, Any]:
        return await self._send("POST", path, body, token)

    async def _get(self, path: str, *, token: str | None) -> dict[str, Any]:
        return await self._send("GET", path, None, token)

    async def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
        token: str | None,
    ) -> dict[str, Any]:
        url = f"{_MP_API}{path}"
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if token:
            headers["Authorization"] = f"Bearer {token}"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            try:
                response = await client.request(
                    method, url, headers=headers, json=body, timeout=self._timeout
                )
            except httpx.HTTPError as exc:
                raise MercadoPagoSplitError(f"http error {method} {path}: {exc}") from exc
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                raise MercadoPagoSplitError(
                    f"{method} {path} → HTTP {response.status_code}: {response.text[:400]}"
                )
            try:
                parsed = response.json()
            except ValueError as exc:
                raise MercadoPagoSplitError(f"{method} {path}: non-JSON body") from exc
            if not isinstance(parsed, dict):
                raise MercadoPagoSplitError(
                    f"{method} {path}: expected dict, got {type(parsed).__name__}"
                )
            return parsed
        finally:
            if owns_client:
                await client.aclose()


def _safe_json(body: bytes) -> dict[str, Any]:
    try:
        parsed = json.loads(body or b"{}")
    except (ValueError, TypeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}
