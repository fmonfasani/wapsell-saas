# P10 — Dashboard implementador (Next.js admin)

## Objetivo
Frontend para administrar tenants, skills globales y ver métricas del servidor.
Local-first: corre contra la API FastAPI, sin auth real (mock SSO).

## Deliverables
- `dashboard/admin/` — Next.js 14 + TypeScript + Tailwind.
- Pantallas mínimas:
  - Listado de tenants (con status, número, modelo).
  - Crear tenant (form → POST a la API).
  - Listado de skills disponibles.
  - Health del backend.
- Cliente HTTP tipado contra los endpoints existentes (`/health`, `/tenants`, `/skills`).
- CI: build de Next.js pasa (`npm run build`). No tests E2E en P10.

## Reglas
- Sin lógica de negocio en el frontend — solo orquesta calls al backend.
- Sin hardcoding de URL: `NEXT_PUBLIC_API_URL` (env).
- Branding en `dashboard/admin/branding/` (logo placeholder + colores).
  `vertical` para la estructura; `product-specific` para branding real.

## NO hacer
- No agregar autenticación real (queda para P13).
- No tocar el dashboard cliente (P11).
- No agregar features que no estén en el spec.

## Verificación
- `npm run lint && npm run build` en `dashboard/admin/`.
- Smoke manual: levantar API + dashboard, listar tenants vacío, crear uno, verlo en la lista.
- `EXTRACTION.md` actualizado.
