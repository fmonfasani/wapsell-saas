# EXTRACTION — Mapa de qué va a cada template

> Brújula para que, el día que extraigamos las 3 templates, sea copiar+pegar y
> no reescribir. Cada vez que se crea un archivo o carpeta nueva, **marcalo acá**
> con su etiqueta. Si no entra en ninguna etiqueta, replantear.

## Etiquetas

- **`core`** → va a **T1 `project-template`** (cualquier proyecto Python serio)
- **`aine`** → va a **T2 `project-template-aine`** (T1 + cableado de AINE)
- **`vertical`** → va a **T3 `whatsapp-sales-saas-template`** (T2 + módulo WhatsApp-sales en blanco)
- **`product-specific`** → NO va a ningún template (branding, configs de cliente, datos)

## Mapa actual

### `core` — infraestructura de calidad reusable
```
pyproject.toml                    # ruff + mypy + pytest config
.github/workflows/ci.yml
.gitignore  .gitattributes  .editorconfig
README.md  CHARTER.md  EXTRACTION.md  docs/PHASES.md
Makefile  (cuando se cree)
tests/conftest.py                 (cuando se cree)
```

### `aine` — wiring del runtime AI (todavía no escrito en Waseller)
```
sdk/waseller/ai/                 (pendiente — no existe aún)
    composition.py                # build_runtime() leyendo OPENROUTER_API_KEY
    codegen.py                    # helper opcional para tareas asistidas
```

### `vertical` — módulo WhatsApp-sales neutro (el grueso de Waseller)
```
sdk/waseller/
    models.py                     # Tenant, Fact, InboundMessage (neutros)
    client.py                     # WasellerClient facade
    tenant/
        manager.py                # TenantManager (CRUD sync + SOUL)
        repository.py             # TenantRepositoryPort + InMemoryTenantRepository
        spawner.py                # TenantSpawner (async) + InMemoryTenantSpawner
        router.py                 # TenantRouter.resolve + UnknownTenantError
        supervisor.py             # TenantSupervisor (bring_up/down/health) + TenantHealth
    agent/
        soul.py                   # SoulBuilder (template parametrizado)
        loop.py                   # AgentLoop.respond(tenant, buyer_id, msg) →
                                  # recall → RAG → SOUL → LLM → AgentTurn (P12b)
    llm/
        port.py                   # LLMPort + LLMMessage/LLMReply + LLMError
                                  # + EchoLLM (default, deterministic) + ScriptedLLM (tests)
                                  # + OpenRouterLLM (httpx, /chat/completions)
    whatsapp/
        webhook.py                # HMAC verify + parser + extract_phone_number_id
        gateway.py                # WhatsAppGatewayPort + OutboundMessage +
                                  # InMemoryGateway + KapsoGateway (httpx, Kapso OSS)
    skills/
        base.py                   # SkillBase + SkillResult
        registry.py               # SkillRegistry + SkillNotFoundError
        catalog_lookup.py         # CatalogLookupSkill (catálogo demo neutro)
        lead_qualifier.py         # LeadQualifierSkill (rule-based scoring)
        sales_closer.py           # SalesCloserSkill (state machine)
    ingestion/
        extractors/
            base.py               # ExtractorPort + ExtractedChunk + UnsupportedFormatError
            csv.py                # CsvExtractor (stdlib)
            pdf.py                # PdfExtractor (pypdf)
            docx.py               # DocxExtractor (python-docx)
            multimedia.py         # MockAudio/Video/Image (mocks; Whisper/Gemini en deploy)
        hindsight.py              # HindsightPort + InMemoryHindsight + PostgresHindsight (tsvector)
        preprocessor.py           # Preprocessor (orquesta extractor → Fact → Hindsight)
    memory/
        buyer.py                  # BuyerMemoryPort + BuyerInteraction +
                                  # InMemoryBuyerMemory (bounded + dialecticDepth)
                                  # + HonchoBuyerMemory (adapter duck-typed)
    events/
        bus.py                    # EventBusPort + Event + InMemoryEventBus
                                  # (publish/subscribe + by_type; ports + adapters)
    onboarding/
        flow.py                   # OnboardingFlow.run(MetaSignupPayload) idempotente
                                  # + slugify() (collision-resolving) + OnboardingError
    security/
        crypto.py                 # TokenCipher (AES-256-GCM) + generate_key +
                                  # key_from_env + CryptoError (cryptography lib)
        log_filter.py             # SecretRedactingFilter + redact() — masks
                                  # OPENROUTER_API_KEY / META_APP_SECRET / *_TOKEN /
                                  # Bearer / sk-... before any log handler sees them
    goal.py                       # Goal/GoalJudge/GoalResult/GoalType/GoalStatus
    client.py                     # incluye buyer_id_for() helper de namespacing tenant-scoped
                                  # + event_bus + onboarding + agent (AgentLoop) + llm (LLMPort)
                                  # (composition root: EchoLLM por default, inyectable)
    cli.py                        # CLI (tenant-create / soul / skills / goal)
infra/postgres/migrations/001_facts.sql  # schema facts + GIN tsvector índice
services/__init__.py              # package marker
services/api/__init__.py          # package marker
services/api/main.py              # FastAPI: /health, /webhook, /skills, /goal,
                                  # + /tenants CRUD (admin: list/create/get/patch/soul)
                                  # + POST /tenants/connect-whatsapp (Meta Embedded Signup) + CORS
services/preprocessor/__init__.py # package marker
services/preprocessor/worker.py   # IngestionQueue + drain + run_forever (asyncio; Celery en deploy)
dashboard/admin/                  # Next.js 14 admin (TS + Tailwind, app router)
    src/lib/api.ts                # cliente HTTP tipado contra services/api
    src/lib/types.ts              # wire types: Tenant, TenantCreateBody, etc.
    src/app/{tenants,skills,health}/...  # pantallas: tenants list/new/[id]/onboard, skills, health
    tailwind.config.ts            # theme.extend.colors.brand = ÚNICO lugar de branding
infra/docker/docker-compose.base.yml
infra/docker/docker-compose.prod.yml  # postgres+redis (internal) + api + nginx,
                                      # restart:always, healthchecks, resource limits
infra/docker/Dockerfile.api           # multi-stage; runtime as UID 10001 non-root
infra/nginx/{nginx.conf,proxy_common.conf}  # TLS termination + HSTS + rate cap
infra/systemd/waseller.service        # boot-time docker compose up/down
infra/scripts/                        # bootstrap / deploy / update / rollback /
                                      # backup / healthcheck — ejecutables en Ubuntu 24.04
docs/DEPLOY.md                        # runbook completo
skills/*/SKILL.md                 # docs de skills neutras
.env.example                      # SOLO claves de variables, sin valores reales
```

### `product-specific` — NO va a ningún template
```
.env                              # secretos reales (ya gitignored)
config/branding/                  # logo, colores, copy de Waseller SA (cuando exista)
config/tenants/*.yaml             # datos de clientes reales (cuando exista)
data/                             # catalogs/leads reales (gitignored)
```

## Reglas operativas

1. Cualquier archivo nuevo se etiqueta acá **antes** de mergear.
2. Si necesitás meter algo `product-specific` en código `vertical`, **parar** —
   esa lógica va detrás de un port o en config, no en el código.
3. Cuando una sección `aine` arranque, se separa físicamente bajo `sdk/waseller/ai/`
   para que la extracción a T2 sea limpia.
4. La extracción real (T1 → T2 → T3) está descrita en los prompts `P91/P92/P93`.

## Estado de extracción

| Template | Estado | Cuándo |
|---|---|---|
| T1 `project-template` | ✅ done 2026-05-31 | https://github.com/fmonfasani/project-template |
| T2 `project-template-aine` | ⏳ pendiente | Después de T1 + Waseller usando AINE |
| T3 `whatsapp-sales-saas-template` | ⏳ pendiente | Después de T2 |
