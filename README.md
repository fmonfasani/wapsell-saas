# Waseller

**An autonomous WhatsApp sales agent, per-tenant, in a box.** Clone the repo,
plug in OpenRouter + Meta WhatsApp credentials, and you have a multi-tenant
SaaS where each customer gets their own sales agent answering buyers on
WhatsApp 24/7.

Reference deployment: **[pipaas.com](https://pipaas.com/health)** (Hetzner VPS,
production-grade since 2026-05-31).

---

## What it actually does

```
Buyer sends WhatsApp message to your tenant's Meta number
        ↓
Meta → webhook POST to your Waseller (HMAC-verified)
        ↓
Tenant router resolves: which of N tenants owns this number?
        ↓
Per-buyer memory recall (last N conversation turns)
        ↓
Tenant-scoped RAG search over the catalog (Hindsight, tsvector)
        ↓
Compose system prompt: tenant SOUL + catalog facts + history + new msg
        ↓
LLM via OpenRouter (or local fallback if no key)
        ↓
Reply sent back via Meta Cloud API → buyer's WhatsApp
```

Every external dependency (LLM provider, gateway, RAG store, buyer memory) is
behind a **Protocol**, so production wiring and test wiring use the exact same
client code. No mocks in production — just different adapter instances.

---

## What's in the box

| Layer | Path | Contents |
|---|---|---|
| **SDK** (PyPI-shaped) | `sdk/waseller/` | `Client` facade · tenants (manager + router + supervisor + spawner) · agent loop (`AgentLoop.respond` does recall → RAG → SOUL → LLM → reply) · skills (lead-qualifier, sales-closer, catalog-lookup) · WhatsApp gateway port + 3 adapters (`InMemory`, `Kapso`, `WhatsAppCloud`) · RAG (in-memory + Postgres tsvector `Hindsight`) · buyer memory (in-memory + Honcho) · onboarding (Meta Embedded Signup) · security (AES-256-GCM `TokenCipher`, secret-redacting log filter) · event bus · goal judge · CLI |
| **API** | `services/api/main.py` | FastAPI: `/health` · `/health/deep` (postgres + openrouter + meta probes, 503 on degraded) · `/webhook` (HMAC-verified) · `/tenants` CRUD · `/tenants/connect-whatsapp` (onboarding, idempotent) · `/tenants/{id}/catalog/facts` (bulk RAG ingest + listing) · `/skills` · `/goal` · CORS · SlowAPI rate limit |
| **Workers** | `services/preprocessor/` | Async queue + drain for ingestion jobs |
| **Gateway** | `services/gateway/` | Pointer to Kapso OSS submodule (optional) |
| **Admin dashboard** | `dashboard/admin/` | Next.js 14 + TypeScript + Tailwind — tenants list/create/detail/onboard, skills, health |
| **Infra** | `infra/` | `docker-compose.{prod,coexist,base}.yml` · `Dockerfile.api` (multi-stage, non-root) · nginx (TLS, HSTS, OCSP stapling, rate cap) · systemd unit · runbook scripts (`bootstrap`, `deploy`, `update`, `rollback`, `backup`, `healthcheck`) · Postgres migrations |
| **Docs** | `docs/` | [`DEPLOY.md`](docs/DEPLOY.md) (clean-VPS runbook) · [`PRODUCTION-LOG.md`](docs/PRODUCTION-LOG.md) (real deploy lessons + 9 gotchas) |

---

## Quickstart (local)

```bash
git clone https://github.com/fmonfasani/waseller.git
cd waseller

python -m pip install -e ".[dev]"

# full gate (lint + type + test) — should be green from minute 0
ruff check . && ruff format --check . && \
  mypy --strict sdk/waseller services tests && \
  pytest -q

# try the CLI
waseller tenant-create --name "Acme Store" --slug acme
waseller soul --name "Acme Store" --slug acme

# run the API (in-memory everything, no real Meta needed)
uvicorn services.api.main:app --reload
# → POST /tenants/connect-whatsapp with a fake phone_number_id
# → POST /webhook with a forged Meta payload (see scripts/smoke-webhook.sh)
```

For the admin dashboard:

```bash
cd dashboard/admin && npm install && npm run dev
# → http://localhost:3000 talks to http://localhost:8000
```

---

## Production deploy

Two paths depending on your VPS:

| Your VPS is… | Use |
|---|---|
| **Empty / dedicated to Waseller** | [`docs/DEPLOY.md`](docs/DEPLOY.md) — `bootstrap.sh` does docker + ufw + certbot + nginx + systemd in one shot |
| **Shared with other services** (Coolify, manual nginx, other sites) | [`docs/PRODUCTION-LOG.md`](docs/PRODUCTION-LOG.md) + [`infra/docker/docker-compose.coexist.yml`](infra/docker/docker-compose.coexist.yml) — coexists with whatever's already there, host nginx proxies to `127.0.0.1:<APP_PORT>` |

After deploy, validate the agent loop end-to-end without depending on Meta:

```bash
./scripts/smoke-webhook.sh --message "test from the smoke script"
# → forges a HMAC-signed POST /webhook with a real Meta payload shape
# → if your outbound is wired, you receive the agent's reply on WhatsApp
```

### Multi-tenant demo

To see the router resolving two tenants with totally different catalogs (and
different policies) on a single deploy, run:

```bash
./scripts/seed-multi-tenant-demo.sh
# → onboards tenant A (zapatillas) on the Meta test number
# → onboards tenant B (cafe)        on a synthetic phone_number_id
# → seeds both catalogs (10 SKUs + 4 policies each)
# → prints 8 ready-to-paste smoke commands that exercise A/A, A/B, B/B, B/A
#   plus policy-by-tenant routing (different hours, different payment methods)
```

The two tenants share zero state — facts queried from A never leak into B's
RAG, and the SOUL each one renders comes from its own metadata. This is the
demo to record when pitching Waseller as multi-tenant SaaS.

---

## The template family

Waseller is the **"client zero"** of a 3-template family. Each is its own public
repo; T2 inherits from T1, T3 inherits from T2:

| Template | What it gives you | Repo |
|---|---|---|
| **T1** Python project starter (any project) | hatchling + ruff + mypy --strict + pytest config, Makefile, CI matrix on Python 3.11/3.12/3.13, zero-dep `scripts/init.py` to rename the sample package on first clone | [`fmonfasani/project-template`](https://github.com/fmonfasani/project-template) |
| **T2** T1 + AI runtime pre-wired | T1 + `aine-platform` dependency, `bootstrap_runtime()` → `AIBundle(runtime, codegen)`, falls back to local LLM if no `OPENROUTER_API_KEY` | [`fmonfasani/project-template-aine`](https://github.com/fmonfasani/project-template-aine) |
| **T3** T2 + full WhatsApp sales vertical | T2 + the entire SDK + services + dashboard + infra you see in *this* repo, brand-neutralized | [`fmonfasani/whatsapp-sales-saas-template`](https://github.com/fmonfasani/whatsapp-sales-saas-template) |

If you want to build something WhatsApp-sales-like for your own brand, **start
from T3**, not from Waseller. Waseller has the production deployment, branding
decisions, and historical commits; T3 is the same code with everything generic.

---

## Status

| Area | State |
|---|---|
| All planned phases (P03–P13) | ✅ done |
| Live deploy at pipaas.com (Hetzner, coexisting with Coolify + 13 sites) | ✅ since 2026-05-31 |
| Outbound: agent reply → buyer's WhatsApp (via `WhatsAppCloudGateway`) | ✅ validated E2E |
| Inbound: real WhatsApp msg from buyer → webhook → agent | ✅ validated via signed forge (`scripts/smoke-webhook.sh`) |
| 3 templates extracted (T1/T2/T3) all public + green CI | ✅ |
| `WhatsAppCloudGateway` adapter (Meta Cloud API direct) + 192 tests passing | ✅ |
| Security: TLS, HSTS, HMAC webhooks, AES-256-GCM for tokens, log secret redaction | ✅ |
| **Client dashboard** (Conversation entity + per-tenant chat UI) | 🟡 deferred until needed |
| **PostgresTenantRepository + PostgresHindsight + PostgresBuyerMemory env-wired in `services/api/main.py`** (set `WASELLER_POSTGRES_URL` → tenants, catalog, AND conversation history persist across restarts) | ✅ |
| **Multi-worker safe state** (all three shared stores in Postgres; bump `--workers` once `WASELLER_POSTGRES_URL` is set) | ✅ |
| **Meta business verification** (to go past dev-mode test-recipient list) | ⏳ user-side admin task |

---

## Architecture in one paragraph

The runtime is built around **ports + adapters**. `WasellerClient` is the
composition root that wires concrete adapter instances behind each Protocol —
`InMemory*` for local/test, `Postgres*` / `Honcho*` / `Kapso*` / `WhatsAppCloud*` /
`OpenRouter*` for production. The `AgentLoop.respond(tenant, buyer_id, text)`
method is the single seam where one message becomes one reply — every external
system is reached through one of those ports, never directly. The `services/api`
layer is thin: it does HMAC verification, tenant routing, calls `agent.respond`,
remembers turns, and sends via `gateway.send_text`. No business logic in HTTP
handlers; no HTTP knowledge in the SDK.

---

## Tech stack

Python 3.11+ · FastAPI · pydantic 2 · SQLAlchemy / Postgres (tsvector for RAG) ·
Redis (rate limiting + Celery queue, optional) · SlowAPI (per-IP rate limit) ·
cryptography (AES-256-GCM) · structlog · httpx · pytest with `asyncio_mode=auto`
· ruff (lint + format) · mypy strict · Hatch (build backend) · Docker multi-stage
· nginx + Let's Encrypt · Next.js 14 + TypeScript + Tailwind (admin dashboard)

Adapters:
- **LLM**: OpenRouter (price-routed across Anthropic/OpenAI/Meta/etc.) + local fallback
- **WhatsApp**: Meta Cloud API direct (`WhatsAppCloudGateway`) OR Kapso OSS gateway
- **RAG**: Postgres tsvector (`PostgresHindsight`) OR in-memory substring
- **Buyer memory**: Honcho OR in-memory ring buffer

---

## Development

| Task | Command |
|---|---|
| Install dev deps | `pip install -e ".[dev]"` |
| Lint + format check | `ruff check . && ruff format --check .` |
| Type check (strict) | `mypy --strict sdk/waseller services tests` |
| Test | `pytest -q` |
| All of the above (what CI runs) | `make check` |
| Build PyPI wheel | `python -m build` |

CI runs on every push and pull request (`.github/workflows/ci.yml`).
**Branch protection on `main`**: requires `Backend · Lint · Type · Test` +
`Dashboard admin · Typecheck · Build` green; no force-push; no deletion. **PR
flow only.**

---

## Contributing

The 5 hard rules ([`CHARTER.md`](CHARTER.md)):

1. **Sealed layers** — sdk · services · skills · infra. No leaking.
2. **No hardcoded client data** — everything through env / tenant config.
3. **Ports + adapters** for every external system. Vendor SDKs never imported
   in product code.
4. **Branding in one layer** — the SDK is brand-neutral; tenant config carries
   the brand.
5. **Green gate before every push** — `make check` must pass locally; CI
   enforces it on `main`.

See also [`EXTRACTION.md`](EXTRACTION.md) for the file-level `core` /
`vertical` / `product-specific` tagging that drove the T1/T2/T3 split.

---

## License

Proprietary. Source is public for transparency and template extraction; usage
in your own product requires permission. See the headers / `pyproject.toml`
classifier.

The three templates (T1/T2/T3) are independent repos with their own licenses
— they're MIT, designed to be cloned and used.
