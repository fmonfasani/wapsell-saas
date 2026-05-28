# HermesSell

WhatsApp Sales SaaS — an AI sales agent per customer over WhatsApp.

**Stack:** Python 3.11 · FastAPI · PostgreSQL · Redis/Celery · OpenRouter (price-sorted
routing) · Hermes Agent · Kapso OSS (WhatsApp) · Hindsight (RAG) · Honcho (buyer memory) ·
Next.js dashboards.

> Status: **Fase 0** — monorepo + SDK skeleton + CI. Building locally with external
> integrations (Meta/WhatsApp, Kapso, Whisper/Gemini) mocked; real wiring is validated at
> deploy time with credentials.

## Layout

```
sdk/hermesell/      SDK (PyPI): client, tenant, agent (SOUL), whatsapp, ingestion, cli
services/api/       FastAPI internal API (health + WhatsApp webhook)
services/preprocessor/  Celery worker: CSV/PDF/DOCX/audio/video → Hindsight (later)
services/gateway/   Kapso OSS submodules (added at integration time)
dashboard/          Next.js admin + client apps (later)
skills/             SKILL.md sales skills (sales-closer, catalog-lookup, …)
infra/              docker-compose, nginx, provisioning scripts
tests/              unit/integration/smoke
```

## Quickstart

```bash
python -m pip install -e ".[dev]"

# quality gate (mirrors CI)
ruff check . && ruff format --check . && mypy sdk/hermesell services tests && pytest

# try the CLI
hermesell tenant-create --name "Acme Store" --slug acme
hermesell soul --name "Acme Store" --slug acme

# run the API
uvicorn services.api.main:app --reload
```

## What works today (Fase 0)

- **SDK skeleton** importable + typed: `HermesSellClient`, `TenantManager`, models.
- **SOULBuilder** — deterministic per-tenant behavioral prompt (tested).
- **WhatsApp webhook** — Meta HMAC-SHA256 verification, subscription handshake, payload
  parsing (tested), wired into the FastAPI service.
- **CLI**, **CI** (ruff + mypy strict + pytest).

## Phase roadmap

See [`docs/PHASES.md`](docs/PHASES.md). Order: 0 repo → 1 VPS → 2 Hermes → 3 gateway →
4 preprocessor → 5 RAG → 6 memory → 7 sales logic → 8 multi-tenant → 9 SDK →
10–11 dashboards → 12 onboarding → 13 security/prod.
