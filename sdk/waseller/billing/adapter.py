"""Mercado Pago HTTP adapter — create preapproval + verify webhook + fetch.

We use the Preapproval API for recurring subscriptions (not Checkout Pro,
which is one-shot). The flow:

1. Backend calls :meth:`create_preapproval` with the plan amount + payer
   email + a unique ``external_reference`` (we use the tenant id).
2. MP returns ``init_point`` (the hosted checkout URL) and the
   ``preapproval_id`` we store locally.
3. Dashboard sends the buyer to ``init_point`` in a new tab; buyer enters
   card, MP confirms.
4. MP fires a webhook (``topic=preapproval``) to our endpoint when the
   status flips. We call :meth:`get_preapproval` to read the current state
   and patch the local row.

All HTTP calls share a single ``httpx.AsyncClient`` so the connection
pool sticks around across webhook bursts. Errors get raised as
:class:`MercadoPagoError` so the API layer can map to 502 / log + retry
without having to remember httpx exception classes.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import hmac
import logging
from typing import Any

import httpx

_log = logging.getLogger("waseller.billing.mercadopago")

_MP_BASE_URL = "https://api.mercadopago.com"
_HTTP_ERROR_THRESHOLD = 400


class MercadoPagoError(RuntimeError):
    """Wraps any error from the MP API — network failure, 4xx/5xx, bad JSON.

    Callers catch this at the boundary; the rest of the codebase never sees
    raw httpx errors."""


@dataclass(slots=True)
class PreapprovalResult:
    """What the dashboard needs to redirect the buyer + persist locally."""

    preapproval_id: str
    init_point: str
    status: str  # MP-side status (pending until buyer authorizes)


class MercadoPagoAdapter:
    """Production-mode MP client. Pass the prod ``access_token`` you got
    from developers.mercadopago.com.ar/panel/credentials.

    Sandbox? Use sandbox credentials — the API surface is identical.
    """

    def __init__(
        self,
        *,
        access_token: str,
        client: httpx.AsyncClient | None = None,
        timeout: float = 15.0,
    ) -> None:
        if not access_token:
            raise MercadoPagoError("access_token is required")
        self._token = access_token
        self._client = client
        self._timeout = timeout

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    async def create_preapproval(
        self,
        *,
        plan_name: str,
        amount_ars: float,
        payer_email: str,
        external_reference: str,
        back_url: str,
        frequency_months: int = 1,
    ) -> PreapprovalResult:
        """Create a recurring subscription. Returns the MP preapproval id and
        the ``init_point`` URL the buyer must visit to authorize the card."""
        payload: dict[str, Any] = {
            "reason": plan_name,
            "external_reference": external_reference,
            "payer_email": payer_email,
            "back_url": back_url,
            "status": "pending",
            "auto_recurring": {
                "frequency": frequency_months,
                "frequency_type": "months",
                "transaction_amount": float(amount_ars),
                "currency_id": "ARS",
            },
        }
        data = await self._post("/preapproval", payload)
        # MP returns ``id``, ``init_point``, ``status`` among many other
        # fields. We surface only what the dashboard needs.
        return PreapprovalResult(
            preapproval_id=str(data.get("id")),
            init_point=str(data.get("init_point", "")),
            status=str(data.get("status", "pending")),
        )

    async def get_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        """Fetch the current state of a preapproval — invoked from the
        webhook handler to refresh the local row."""
        return await self._get(f"/preapproval/{preapproval_id}")

    async def cancel_preapproval(self, preapproval_id: str) -> dict[str, Any]:
        """Cancel an active subscription. MP treats ``status=cancelled`` as
        terminal — there is no resume; the buyer would need a new
        preapproval."""
        return await self._put(f"/preapproval/{preapproval_id}", {"status": "cancelled"})

    # ------------------------------------------------------------------
    # HTTP helpers
    # ------------------------------------------------------------------
    async def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._send("POST", path, body)

    async def _get(self, path: str) -> dict[str, Any]:
        return await self._send("GET", path, None)

    async def _put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        return await self._send("PUT", path, body)

    async def _send(
        self,
        method: str,
        path: str,
        body: dict[str, Any] | None,
    ) -> dict[str, Any]:
        url = f"{_MP_BASE_URL}{path}"
        client = self._client or httpx.AsyncClient(timeout=self._timeout)
        owns_client = self._client is None
        try:
            try:
                response = await client.request(
                    method,
                    url,
                    headers=self._headers,
                    json=body,
                    timeout=self._timeout,
                )
            except httpx.HTTPError as exc:
                raise MercadoPagoError(f"http error calling {method} {path}: {exc}") from exc
            if response.status_code >= _HTTP_ERROR_THRESHOLD:
                # MP's error body is usually a JSON with ``message`` +
                # ``cause`` array — preserve the text so operators see why.
                text = response.text[:400]
                raise MercadoPagoError(
                    f"{method} {path} returned HTTP {response.status_code}: {text}"
                )
            try:
                parsed = response.json()
            except ValueError as exc:
                raise MercadoPagoError(f"{method} {path} returned non-JSON body") from exc
            if not isinstance(parsed, dict):
                raise MercadoPagoError(
                    f"{method} {path}: expected dict, got {type(parsed).__name__}"
                )
            return parsed
        finally:
            if owns_client:
                await client.aclose()


def verify_mp_webhook_signature(
    secret: str,
    body: bytes,
    signature_header: str,
    request_id_header: str,
    data_id: str,
) -> bool:
    """Verify a MP webhook signature.

    MP's webhook signing scheme: the ``x-signature`` header contains a comma-
    separated list ``ts=<unix>,v1=<sha256>`` where the v1 hash is HMAC-SHA256
    over the canonical string
    ``id:<data_id>;request-id:<x-request-id>;ts:<ts>``
    keyed by the webhook secret.

    Reference: https://www.mercadopago.com.ar/developers/en/docs/your-integrations/notifications/webhooks#bookmark_validation
    """
    if not secret:
        # Allow disabling signature checks when the operator hasn't set
        # MP_WEBHOOK_SECRET yet — log + accept. Prevents the system from
        # breaking on day one before the operator has even created the
        # webhook in MP's panel.
        _log.warning("MP webhook signature check skipped (no secret configured)")
        return True

    parts: dict[str, str] = {}
    for chunk in signature_header.split(","):
        if "=" not in chunk:
            continue
        k, _, v = chunk.strip().partition("=")
        parts[k.strip()] = v.strip()

    ts = parts.get("ts")
    provided = parts.get("v1")
    if not ts or not provided:
        return False

    canonical = f"id:{data_id};request-id:{request_id_header};ts:{ts};"
    expected = hmac.new(
        secret.encode("utf-8"), canonical.encode("utf-8"), hashlib.sha256
    ).hexdigest()
    return hmac.compare_digest(expected, provided)
