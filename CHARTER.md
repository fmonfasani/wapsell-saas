# HermesSell — Charter (la constitución del proyecto)

> Documento corto y obligatorio. Cualquier cambio de scope se compara contra esto
> antes de aceptarse. Si una decisión no encaja con el Norte o rompe una de las
> 5 reglas, se rechaza o se reabre el Charter explícitamente.

## Norte (no cambia)

**HermesSell = SaaS de agentes de ventas automáticos por WhatsApp.**

Una empresa contrata HermesSell → su número de WhatsApp pasa a estar atendido 24/7
por un agente de IA que entiende su catálogo, conversa con compradores, califica
leads y cierra ventas, todo deterministico y auditable.

Todo lo que se construya tiene que aportar a esto. Si no aporta directa o
indirectamente, no se construye ahora.

## Las 5 reglas (no se relajan)

1. **Capas estancas.** `sdk/` (lógica neutra), `services/` (transporte: FastAPI / Celery),
   `skills/` (lógica de venta neutra), `infra/` (Docker / nginx). Nada de WhatsApp
   dentro de `skills/`. Nada de Meta dentro de `sdk/`. Nada de business logic en
   `services/` (los routers solo orquestan).
2. **Cero hardcoding de cliente.** Ningún nombre de empresa, dominio, número de
   teléfono, modelo de LLM, prompt customer-specific en el código. Todo por env /
   `tenant.*` / `settings.*`. Si aparece "HermesSell SA" o "ENACOM" o un teléfono
   real en código, es un bug arquitectónico.
3. **Ports + adapters a rajatabla.** Meta detrás de un port. OpenRouter detrás de
   un port. Hindsight detrás de un port. Honcho detrás de un port. En tests se
   inyectan mocks; en prod, el adapter real. Nada llama a un SDK vendor directo
   desde el dominio.
4. **Branding / config en una sola capa.** `config/branding/`, `config/tenant.yaml`,
   `.env`. El día que extraigamos templates, esa capa va vacía con `<placeholder>`.
5. **Gate verde antes de commit.** `ruff check . && ruff format --check . &&
   mypy sdk/hermesell services tests && pytest`. Sin excepciones. Si un cambio no
   pasa el gate, no se commitea — se arregla o se descarta.

## Propuesta de 4 puntos (el plan)

1. **Ahora — Charter + mapa de extracción.** Este documento + `EXTRACTION.md`.
   Brújula arquitectónica antes de seguir escribiendo código.
2. **Después — Arreglar Fase 7 a verde y commitear.** La lógica de skills + goals
   está escrita pero rota (3 tests + lint/mypy). Se arregla respetando las 5 reglas
   y se commitea como Fase 7 limpia.
3. **Después — Seguir las fases.** Una por una (Fase 8 multi-tenant → 4 preprocesador
   → 5 RAG → 6 memoria → 9 SDK → 3 gateway → 10/11 dashboards → 12 onboarding →
   13 seguridad/prod). Cada fase = un prompt en `prompts/` con scope acotado.
4. **Cuando HermesSell esté operativo — Extraer las 3 templates.**
   T1 `project-template` → T2 `project-template-aine` → T3 `whatsapp-sales-saas-template`.
   El mapa de `EXTRACTION.md` hace que esto sea copiar+pegar, no reescribir.

## Reglas de scope (lo que NO hacemos)

- ❌ No deployamos a Hetzner hasta tener Fase 7-9 + 13 verdes localmente.
- ❌ No agregamos dependencias que no aporten al Norte (ni "qué linda esta lib").
- ❌ No usamos componentes externos sin verificar primero que existen / se instalan.
- ❌ No mezclamos código de HermesSell con HookClose (son proyectos separados).
- ❌ No subimos HermesSell a GitHub público hasta que esté productivo y auditado
  (puede llevar info de clientes; cuando se sube, va privado).

## Métricas de "está listo para producción"

HermesSell se considera **production-ready** cuando, en orden:

- [ ] Fase 7 verde + commiteada
- [ ] Fases 4, 5, 6 verdes + commiteadas
- [ ] Fase 8 (multi-tenant) verde
- [ ] Fase 9 (SDK) empaquetable y testeada
- [ ] Fase 3 (Kapso gateway) integrada (al menos webhook end-to-end con test number Meta)
- [ ] Fase 13 (TLS + rate limiting + secrets) implementada en el deploy kit
- [ ] Smoke test end-to-end: un mensaje de WhatsApp llega y un agente responde con
      lookup real al catálogo (mockeable hasta el deploy)
- [ ] Deploy validado en una VPS de staging

Recién ahí se considera el deploy de producción.
