# P93 — Extraer T3 `whatsapp-sales-saas-template`

## Objetivo
"HermesSell en blanco": un emprendedor clona T3, conecta sus LLMs (OpenRouter)
y su número de Meta, y tiene un SaaS de ventas por WhatsApp funcionando bajo su
propia marca.

## Pre-requisito
- T2 mergeada y testeada (P92 done).
- HermesSell production-ready (todas las fases verdes y deployada en una VPS al
  menos una vez como validación).

## Cómo extraer
1. Repo nuevo `whatsapp-sales-saas-template` clonado de T2.
2. Copiar **solo lo marcado `vertical`** en [`../EXTRACTION.md`](../EXTRACTION.md):
   - `sdk/{{ project_slug }}/` con todo el módulo: models, client, tenant, agent,
     whatsapp, skills, ingestion, memory, onboarding, security.
   - `services/api/` completo.
   - `services/preprocessor/`.
   - `services/gateway/` (con README pidiendo agregar los submodules de Kapso).
   - `skills/*/SKILL.md`.
   - `infra/docker/`, `infra/nginx/`, `infra/scripts/`, `infra/systemd/`.
   - `dashboard/admin/` y `dashboard/client/` con branding en `<placeholder>`.
3. Renombrar referencias a `hermesell` → `{{ project_slug }}` en imports/strings.
   Conservar el SDK como nombre genérico configurable.
4. Asegurar que `config/branding/` y `config/tenants/` están **vacíos** con
   archivos `.example` solo.
5. README + `docs/QUICKSTART.md`: cómo levantar el SaaS propio
   (clone → env → Meta test number → `make up` → primer mensaje).
6. CI corre con mocks y pasa.

## Reglas
- Cero referencias a "HermesSell" (la marca) en T3. La marca vive en el cliente.
- Cero datos de tenant real. Solo `.example`.
- Branding genérico (placeholder).

## NO hacer
- No incluir nada `product-specific` (datos de clientes reales).
- No subir credenciales.
- No publicar a PyPI todavía.

## Verificación
- Clonar T3 a `/tmp/test`, completar `.env` con keys propias, `make up`, smoke
  manual: webhook recibe mensaje mock, agente responde.
- Gate verde.
- Marcar T3 como ✅ en `EXTRACTION.md`.

## Resultado final
3 repos listos: T1 (genérico Python), T2 (genérico + AI), T3 (SaaS WhatsApp).
HermesSell sigue siendo el "cliente cero" que valida T3 en producción.
