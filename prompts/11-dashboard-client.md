# P11 — Dashboard cliente final (Next.js)

## Objetivo
La app que ve **el cliente final** (la empresa que usa HermesSell para vender):
bandeja de mensajes, vista Kanban del agente, analítica simplificada, control de
catálogo (drag & drop al preprocesador).

## Deliverables
- `dashboard/client/` — Next.js 14 + TypeScript + Tailwind.
- Pantallas mínimas:
  - Inbox (lista de conversaciones por tenant).
  - Kanban (cards con stage: NEW / QUALIFIED / NEGOTIATING / CLOSED).
  - Catálogo: lista de Facts + uploader (POST archivo → preprocesador).
  - Analítica básica: # mensajes recibidos / # ventas cerradas / tiempo medio.
- CI: build pasa.

## Reglas
- Igual que P10: sin lógica de negocio, sin hardcoding, branding en `branding/`.
- Multi-tenant aware: el cliente solo ve su propio tenant (token / header).

## NO hacer
- No agregar auth real (P13).
- No tocar el dashboard admin.

## Verificación
- Build + lint verdes.
- Smoke manual end-to-end: upload de CSV → aparece en Catálogo → query desde Inbox.
