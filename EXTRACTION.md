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
    agent/soul.py                 # SoulBuilder (template parametrizado)
    whatsapp/webhook.py           # HMAC verify + parser + extract_phone_number_id
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
    goal.py                       # Goal/GoalJudge/GoalResult/GoalType/GoalStatus
    client.py                     # incluye buyer_id_for() helper de namespacing tenant-scoped
    cli.py                        # CLI (tenant-create / soul / skills / goal)
infra/postgres/migrations/001_facts.sql  # schema facts + GIN tsvector índice
services/__init__.py              # package marker
services/api/__init__.py          # package marker
services/api/main.py              # FastAPI: /health, /webhook (con tenant router), /skills, /goal
services/preprocessor/__init__.py # package marker
services/preprocessor/worker.py   # IngestionQueue + drain + run_forever (asyncio; Celery en deploy)
infra/docker/docker-compose.base.yml
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
| T1 `project-template` | ⏳ pendiente | Después de Fase 13 |
| T2 `project-template-aine` | ⏳ pendiente | Después de T1 + Waseller usando AINE |
| T3 `whatsapp-sales-saas-template` | ⏳ pendiente | Después de T2 |
