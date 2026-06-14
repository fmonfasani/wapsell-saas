# PLAN-PAYMENTS-SPLIT — Wapsell como socio de las ventas (comisión 5%)

> Estado: DISEÑO (2026-06-14). Orden de implementación: **Mercado Pago primero**, Stripe después.
> Objetivo: cobrar un % de cada venta que el bot cierra dentro de WhatsApp, automáticamente,
> sin perseguir al vendedor.

---

## 0. Dos modelos de ingreso — no confundir

| | `billing/` (YA EXISTE) | `payments/` (NUEVO, este doc) |
|---|---|---|
| Qué cobra | Suscripción SaaS de Wapsell al vendedor | Comisión 5% sobre la venta del vendedor a SU cliente |
| Quién paga | El tenant (vendedor) → Wapsell | El comprador final → vendedor (y Wapsell retiene 5%) |
| API MP | Preapproval (recurring) | **Checkout Pro / Preferences + `marketplace_fee`** |
| API Stripe | (a futuro) Billing/Subscriptions | **Connect + `application_fee_amount`** |
| Quién está en el flujo de plata | Wapsell cobra directo | Wapsell es **marketplace/plataforma**, hace el *split* |

Los dos pueden coexistir: un plan barato fijo + success fee. Este doc cubre **solo el segundo**.

**Regla de oro del 5% automático:** solo se puede retener la comisión si la plata
**pasa por un link de pago generado por Wapsell**. Si el vendedor cobra por fuera
(efectivo, su propio MP), no hay split posible — solo trackeo + factura manual (fuera de alcance).

---

## 1. Arquitectura — módulo nuevo `sdk/wapsell/payments/`

Mismo patrón que `billing/`: Port + adapters + service + repository + models.

```
sdk/wapsell/payments/
├── __init__.py
├── port.py            # PaymentProviderPort (Protocol) — contrato común
├── models.py          # MerchantConnection, PaymentLink, Payment, Commission (pydantic)
├── repository.py      # *RepositoryPort (las 4 entidades)
├── service.py         # PaymentsService — orquesta link → webhook → comisión → evento
├── routing.py         # elige provider por país/preferencia del vendedor
└── providers/
    ├── __init__.py
    ├── mercadopago.py # MercadoPagoMarketplaceAdapter   (FASE 1)
    └── stripe.py      # StripeConnectAdapter            (FASE 2)
```

El `PaymentProviderPort` es la clave: el `PaymentsService` no sabe si abajo hay MP o Stripe.
Eso permite "los dos" sin duplicar lógica de dominio.

```python
# payments/port.py
class PaymentProviderPort(Protocol):
    name: str  # "mercadopago" | "stripe"

    async def start_merchant_onboarding(self, *, tenant_id: str, return_url: str) -> OnboardingLink:
        """Devuelve la URL OAuth/Connect que el vendedor visita una vez
        para autorizar a Wapsell a cobrar en su nombre."""

    async def complete_merchant_onboarding(self, *, tenant_id: str, callback_params: dict) -> MerchantConnection:
        """Cierra el OAuth: guarda el token/account_id del vendedor."""

    async def create_payment_link(
        self, *, connection: MerchantConnection, amount: int, currency: str,
        fee_bps: int, external_reference: str, description: str,
    ) -> CreatedLink:
        """Crea el link de pago CON el split ya embebido (fee_bps = 500 → 5%)."""

    def verify_webhook(self, *, body: bytes, headers: Mapping[str, str]) -> WebhookEvent | None:
        """Valida firma + normaliza el evento del provider a WebhookEvent."""

    async def fetch_payment(self, *, connection: MerchantConnection, provider_payment_id: str) -> PaymentSnapshot:
        """Lee el estado canónico del pago para reconciliar."""
```

> `fee_bps` = basis points (500 = 5,00 %). Enteros, igual que `price_ars_cents` en `plans.py`,
> para no arrastrar floats.

---

## 2. Modelo de dominio (`payments/models.py`)

```
MerchantConnection   # vendedor ↔ provider, 1 por (tenant, provider)
  tenant_id, provider, status(pending|active|revoked)
  mp_user_id | stripe_account_id
  access_token (cifrado con security/crypto.py)  ← solo MP
  created_at, updated_at

PaymentLink          # un link generado para una venta concreta
  id, tenant_id, contact_id, deal_id?, provider
  amount, currency, fee_bps
  provider_pref_id | stripe_session_id
  url, status(open|paid|expired|cancelled)
  external_reference  ← clave para casar el webhook
  created_at

Payment              # el pago confirmado (viene del webhook)
  id, link_id, provider_payment_id
  amount, currency, status(approved|refunded|...)
  paid_at

Commission           # nuestra tajada, registrada para reporting/conciliación
  id, payment_id, tenant_id
  gross_amount, fee_bps, fee_amount, net_to_merchant
  provider, created_at
```

`Commission` es lo que después alimenta tu dashboard de "cuánto generó Wapsell".

---

## 3. Cómo funciona el SPLIT — Mercado Pago Marketplace (FASE 1)

MP lo llama **"split de pagos" / Marketplace**. Dos piezas:

### 3.1 Onboarding del vendedor (OAuth, una sola vez)
1. Creás una **aplicación Marketplace** en el panel de MP (distinta de la app de Preapproval).
   Te da `client_id` + `client_secret` + redirect URI.
2. El vendedor entra al dashboard de Wapsell → "Conectar Mercado Pago" → lo mandás a:
   ```
   https://auth.mercadopago.com/authorization?client_id=APP_ID&response_type=code
        &platform_id=mp&redirect_uri=https://app.wapsell.com/payments/mp/callback
   ```
3. El vendedor autoriza → MP redirige con `?code=...` → vos POSTeás a
   `/oauth/token` y obtenés el **`access_token` del vendedor** + su `user_id`.
4. Guardás eso en `MerchantConnection` (token cifrado con tu `security/crypto.py`).

> A partir de acá, Wapsell puede crear pagos **en nombre del vendedor** usando SU token.

### 3.2 Crear el link con comisión
Cuando el bot cierra la venta, llamás a **Preferences** (Checkout Pro) usando el token del vendedor
y agregás `marketplace_fee`:

```python
# providers/mercadopago.py  — create_payment_link
payload = {
    "items": [{"title": description, "quantity": 1,
               "unit_price": amount / 100, "currency_id": currency}],  # ARS/BRL/MXN
    "marketplace_fee": round(amount * fee_bps / 10_000) / 100,         # 5% → tu tajada
    "external_reference": external_reference,
    "notification_url": "https://api.wapsell.com/payments/mp/webhook",
    "back_urls": {...},
}
# OJO: este POST va con el access_token DEL VENDEDOR (connection.access_token),
# NO con el tuyo. Tu app marketplace se identifica por el header X-meli-...
data = await self._post("/checkout/preferences", payload, token=connection.access_token)
return CreatedLink(url=data["init_point"], provider_pref_id=data["id"])
```

**Flujo de plata:** comprador paga la preferencia → MP acredita al vendedor y
**retiene tu `marketplace_fee` → tu cuenta colectora** automáticamente. Cero intervención.

### 3.3 Webhook
- MP pega a `notification_url` con `topic=payment&id=...`.
- Verificás firma (podés reusar el patrón de `verify_mp_webhook_signature` de [billing/adapter.py:180](sdk/wapsell/billing/adapter.py#L180)).
- `fetch_payment` lee `/v1/payments/{id}` (con token del vendedor) → status `approved`.
- El service crea `Payment` + `Commission` y emite el evento (sección 5).

---

## 4. Cómo funciona el SPLIT — Stripe Connect (FASE 2)

Stripe es el camino **internacional** real (135+ países). Lo llamás **Connect**.

### 4.1 Onboarding del vendedor (Express accounts)
1. Activás **Connect** en tu dashboard de Stripe (sos la "platform").
2. `stripe.Account.create(type="express", country=..., ...)` → te da `acct_XXX`.
3. `stripe.AccountLink.create(account=acct_XXX, type="account_onboarding", ...)`
   → URL hosteada por Stripe; el vendedor completa sus datos/banco.
4. Guardás `stripe_account_id` en `MerchantConnection` (Stripe no te da un token de
   larga vida del vendedor; operás con TU api key + el `account_id`).

### 4.2 Crear el link con comisión — "destination charge"
```python
# providers/stripe.py — create_payment_link
session = stripe.checkout.Session.create(
    mode="payment",
    line_items=[{"price_data": {"currency": currency,
                                "product_data": {"name": description},
                                "unit_amount": amount},  # ya en centavos
                 "quantity": 1}],
    payment_intent_data={
        "application_fee_amount": round(amount * fee_bps / 10_000),   # tu 5%
        "transfer_data": {"destination": connection.stripe_account_id},
    },
    client_reference_id=external_reference,
    success_url=..., cancel_url=...,
)
return CreatedLink(url=session.url, stripe_session_id=session.id)
```

**Flujo de plata:** comprador paga → Stripe manda el neto al vendedor (`destination`)
y tu `application_fee_amount` cae en **tu balance de plataforma**. Idéntico resultado que MP.

### 4.3 Webhook
- Stripe pega a `/payments/stripe/webhook` con `checkout.session.completed`.
- Verificás con `stripe.Webhook.construct_event(body, sig_header, endpoint_secret)`.
- Creás `Payment` + `Commission` + evento. Mismo `PaymentsService`, distinto adapter.

---

## 5. Integración con el flujo de WhatsApp (lo que une todo)

Dos puntos de enganche en el código que YA tenés:

### 5.1 Generar el link DENTRO del chat
El `sales_closer` skill ([skills/sales_closer.py](sdk/wapsell/skills/sales_closer.py)) es el lugar natural.
Cuando detecta intención de compra + monto acordado, en vez de decir "coordinamos pago",
llama a `PaymentsService.create_link(...)` y manda el `init_point`/`session.url` por WhatsApp:

> "¡Listo María! Pagá tu reserva acá 👉 https://mpago.la/xxxx — apenas se acredite te confirmo."

Esto **mejora el producto** (cierra en el chat) y **garantiza el 5%** (la plata pasa por vos).

### 5.2 Cerrar el deal cuando se acredita
Hoy el `CrmExtractor` ya infiere `stage_transition.to = "closed_won"` desde el texto
([extractor.py:140](sdk/wapsell/crm/extractor.py#L140)), pero eso es una *inferencia blanda*.
Con el webhook de pago tenés la **señal dura**: cuando llega `payment.approved`, el
`PaymentsService`:
1. crea `Payment` + `Commission`,
2. mueve el deal a `closed_won` (señal real, no inferida),
3. publica `payment.completed` en el event bus.

```python
# payments/service.py (esqueleto)
async def reconcile_from_webhook(self, evt: WebhookEvent) -> None:
    link = self._repo.get_link_by_reference(evt.external_reference)
    if link is None: return
    snap = await self._provider_for(link).fetch_payment(...)
    if snap.status != "approved": return
    payment = self._repo.add_payment(Payment.from_snapshot(link, snap))
    fee = round(payment.amount * link.fee_bps / 10_000)
    self._repo.add_commission(Commission(
        payment_id=payment.id, tenant_id=link.tenant_id,
        gross_amount=payment.amount, fee_bps=link.fee_bps,
        fee_amount=fee, net_to_merchant=payment.amount - fee, provider=link.provider))
    await self._bus.publish(Event("payment.completed",
        {"tenant_id": link.tenant_id, "deal_id": link.deal_id,
         "amount": payment.amount, "fee_amount": fee}))
```

Un subscriber del bus (sección 5.3 de PLAN-CRM) mueve el deal a `closed_won` y dispara el aprendizaje
de conversión por persona que ya tenés.

---

## 6. Routing — "los dos" sin if-spaghetti

`payments/routing.py` elige el provider por vendedor:

```python
def pick_provider(connection_set, *, buyer_country: str) -> PaymentProviderPort:
    # Preferencia explícita del vendedor gana; si no, por país.
    # AR/BR/MX con MP conectado → MP. Resto → Stripe.
```

Cada `MerchantConnection` es por-provider, así un vendedor puede tener ambos
(MP para clientes locales, Stripe para internacionales) y el service elige en runtime.

---

## 7. Config / env nuevos

```
# Mercado Pago Marketplace (FASE 1)
MP_MARKETPLACE_CLIENT_ID=
MP_MARKETPLACE_CLIENT_SECRET=
MP_MARKETPLACE_REDIRECT_URI=https://app.wapsell.com/payments/mp/callback
MP_PAYMENTS_WEBHOOK_SECRET=
WAPSELL_DEFAULT_FEE_BPS=500            # 5%

# Stripe Connect (FASE 2)
STRIPE_SECRET_KEY=
STRIPE_CONNECT_WEBHOOK_SECRET=
STRIPE_CONNECT_RETURN_URL=https://app.wapsell.com/payments/stripe/return
```

---

## 8. Fases de implementación (MP primero, como pediste)

**FASE 1 — Mercado Pago Marketplace**
1. [x] `payments/` scaffolding: port, models, repository (in-memory). — `sdk/wapsell/payments/`
2. [x] `MercadoPagoMarketplaceAdapter`: OAuth + preference con `marketplace_fee` + webhook. — `payments/providers/mercadopago.py`
4. [x] `PaymentsService.create_link` + `reconcile_from_webhook` + `Commission`. — `payments/service.py`
6. [x] Tests: onboarding, link con fee, webhook, idempotencia, no-aprobado. — `tests/test_payments.py` (20 verde)
3. [ ] Endpoints API: `POST /payments/mp/onboard`, `GET /payments/mp/callback`, `POST /payments/mp/webhook`.
5. [ ] Enganche en `sales_closer` (mandar link por WhatsApp en stage CONFIRM).
6b. [ ] Postgres repos + migración `infra/postgres/migrations/0XX_payments.sql`.
7. [ ] Dashboard: pantalla "Conectar MP" + tabla de comisiones.

> Falta wiring real: composition root (inyectar el adapter con `MP_MARKETPLACE_*` +
> `TokenCipher`) y los endpoints FastAPI en `services/api/main.py`.

**FASE 2 — Stripe Connect** (mismo service, nuevo adapter)
8. `StripeConnectAdapter` (Express onboarding + destination charge + webhook).
9. Endpoints `/payments/stripe/*`.
10. `routing.py` para elegir provider por país.
11. Tests equivalentes.

**FASE 3 — Producto/Reporting**
12. Dashboard de revenue (MRR de comisiones), conciliación, refunds.
13. Fee configurable por tenant/plan (success-fee vs híbrido).

---

## 9. Cosas que hay que tener en cuenta (riesgos)

- **Cuentas requeridas:** MP necesita app Marketplace aprobada; Stripe necesita Connect habilitado
  y posible revisión de "platform". Empezá los trámites ya — pueden tardar.
- **Refunds / contracargos:** si el comprador pide devolución, MP/Stripe revierten también tu fee
  (proporcional). El `Commission` debe poder marcarse `refunded`.
- **Impuestos / facturación:** retener 5% te convierte en intermediario → revisar implicancias fiscales
  (AFIP / IVA sobre comisión). No es código, pero es bloqueante para producción.
- **KYC del vendedor:** Stripe exige onboarding completo (banco, identidad) antes de transferir.
  Un vendedor a medio onboardear no puede recibir pagos → manejar `status=pending`.
- **Moneda:** MP es ARS/BRL/MXN; Stripe global. El `currency` viaja en cada `PaymentLink`,
  el routing decide. "Internacional + ML primero" funciona: MP cubre LATAM, Stripe el resto.
```
