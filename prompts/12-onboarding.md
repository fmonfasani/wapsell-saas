# P12 — Onboarding flow (Meta Embedded Signup)

## Objetivo
Que un cliente nuevo se conecte a Waseller con **un click**: integra Meta
Embedded Signup → autoriza el número → Waseller levanta su tenant
automáticamente (registro + SOUL.md generado + Hindsight inicializado + spawn).

## Deliverables
- `services/api/routers/onboarding.py` — endpoint `POST /tenants/connect-whatsapp`
  (recibe el callback de Meta Embedded Signup).
- `sdk/waseller/onboarding/flow.py` — `OnboardingFlow.run(meta_payload)` que:
  1. Crea el tenant en el repository.
  2. Renderiza SOUL.md por default.
  3. Inicializa Hindsight (in-memory ahora; Postgres en deploy).
  4. Llama al `TenantSupervisor.spawn` (in-memory por default).
  5. Emite evento `tenant.onboarded`.
- Frontend: hook en `dashboard/admin/` con el SDK de Meta Embedded Signup.
- Tests: el flow es idempotente; un mismo `phone_number_id` no crea duplicados.

## Reglas
- Meta Embedded Signup detrás del controller; el flow es agnóstico del payload.
- Onboarding `vertical`. Branding `product-specific`.

## NO hacer
- No verificar negocio en Meta (manual / deploy-time).
- No agregar billing.

## Verificación
- Gate verde.
- Smoke con payload mock de Meta: tenant creado, SOUL renderizado, supervisor llamado.
