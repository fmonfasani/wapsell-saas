# HermesSell — Prompts (orden de ejecución)

Cada prompt es un **paquete de trabajo acotado**. Tiene Objetivo, Deliverables,
las 5 reglas del [`../CHARTER.md`](../CHARTER.md) como restricciones, y un
"NO hacer" explícito (anti-scope-creep). Se ejecutan en orden.

| # | Prompt | Fase del spec | Estado |
|---|---|---|---|
| 00 | [Charter & extraction map](00-charter.md) | meta | ✅ done |
| 07 | [Sales logic — fix a verde](07-sales-logic-fix.md) | Fase 7 | ✅ done |
| 08 | [Multi-tenant orchestrator](08-multi-tenant.md) | Fase 8 | ✅ done |
| 04 | [Preprocesador multimodal](04-preprocessor.md) | Fase 4 | ⏳ next |
| 05 | [RAG + ingesta (Hindsight)](05-rag-ingestion.md) | Fase 5 | ⏳ |
| 06 | [Memoria de comprador (Honcho)](06-buyer-memory.md) | Fase 6 | ⏳ |
| 09 | [SDK packaging (PyPI)](09-sdk-packaging.md) | Fase 9 | ⏳ |
| 03 | [Gateway WhatsApp (Kapso)](03-gateway-kapso.md) | Fase 3 | 🟡 webhook done |
| 10 | [Dashboard implementador (Next.js admin)](10-dashboard-admin.md) | Fase 10 | ⏳ |
| 11 | [Dashboard cliente (Next.js client)](11-dashboard-client.md) | Fase 11 | ⏳ |
| 12 | [Onboarding (Meta Embedded Signup)](12-onboarding.md) | Fase 12 | ⏳ |
| 13 | [Seguridad y producción](13-security-prod.md) | Fase 13 | ⏳ |
| 90 | [Push a GitHub privado](90-github-push.md) | post-prod | ⏳ |
| 91 | [Extraer T1 `project-template`](91-extract-t1.md) | post-prod | ⏳ |
| 92 | [Extraer T2 `project-template-aine`](92-extract-t2.md) | post-prod | ⏳ |
| 93 | [Extraer T3 `whatsapp-sales-saas-template`](93-extract-t3.md) | post-prod | ⏳ |

## Reglas comunes a TODOS los prompts (heredadas del Charter)

1. **Capas estancas** (sdk/services/skills/infra).
2. **Cero hardcoding de cliente.**
3. **Ports + adapters** para todo lo externo.
4. **Branding / config en una sola capa.**
5. **Gate verde antes de commit** (ruff + ruff format + mypy strict + pytest).

Cada prompt termina con un bloque "Verificación" que valida estas 5.

## Cómo aplicarlos

1. Lees el prompt entero.
2. Branch nueva: `git checkout -b feat/pNN-<slug>`.
3. Implementás solo lo que dice el prompt. Nada más.
4. Gate verde + commit + (eventualmente) PR cuando el repo esté en GitHub.
5. Actualizás `EXTRACTION.md` con los archivos nuevos etiquetados.
6. Marcás el prompt como ✅ acá.
