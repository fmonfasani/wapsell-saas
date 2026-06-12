"""Waseller internal API (FastAPI).

Fase 0/3/7/10: health, WhatsApp webhook, skills, goals, tenants CRUD (admin).
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
import logging
import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from waseller.auth import (
    AuthError,
    AuthService,
    InMemorySessionRepository,
    InMemoryUserRepository,
    PostgresSessionRepository,
    PostgresUserRepository,
    SessionRepositoryPort,
    UserRepositoryPort,
)
from waseller.client import WasellerClient, buyer_id_for
from waseller.goal import Goal, GoalType
from waseller.handoff import (
    HandoffNotifierPort,
    HttpHandoffNotifier,
    NullHandoffNotifier,
)
from waseller.inbox import (
    BotPausePort,
    InMemoryBotPauseRepository,
    PostgresBotPauseRepository,
)
from waseller.ingestion.hindsight import HindsightPort, InMemoryHindsight, PostgresHindsight
from waseller.llm.port import EchoLLM, LLMPort, OpenRouterLLM
from waseller.memory.buyer import (
    BuyerInteraction,
    BuyerMemoryPort,
    InMemoryBuyerMemory,
    PostgresBuyerMemory,
)
from waseller.models import (
    Fact,
    HandoffConfig,
    InboundMessage,
    MessageTemplate,
    SoulConfig,
    TemplateCategory,
    TemplateStatus,
    Tenant,
    User,
    UserRole,
)
from waseller.onboarding import MetaSignupPayload, OnboardingError
from waseller.security.log_filter import install_redaction
from waseller.templates import (
    InMemoryTemplateRepository,
    PostgresTemplateRepository,
    TemplateRepositoryPort,
)
from waseller.tenant import (
    InMemoryTenantRepository,
    PostgresTenantRepository,
    TenantRepositoryPort,
)
from waseller.whatsapp.gateway import InMemoryGateway, WhatsAppCloudGateway, WhatsAppGatewayPort
from waseller.whatsapp.webhook import (
    extract_phone_number_id,
    parse_messages,
    verify_signature,
    verify_subscription,
)

# Install secret-redacting log filter at module import so it covers every later
# `logging.getLogger(...)` call — handlers attached after this still see the
# filter because it lives on the root logger.
install_redaction()


def _build_gateway() -> WhatsAppGatewayPort:
    """Pick the outbound gateway based on env. WhatsApp Cloud API is preferred
    in prod; fall back to InMemoryGateway when no Meta credentials are present
    (dev, CI, smoke tests). Kapso wiring is out of scope — inject manually if
    you run an OSS gateway."""
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    phone_id = os.environ.get("META_PHONE_NUMBER_ID", "").strip()
    if token and phone_id:
        # httpx import deferred so this module stays import-safe in environments
        # without httpx (it's a core dep, so this is belt-and-braces).
        import httpx  # noqa: PLC0415

        return WhatsAppCloudGateway(
            client=httpx.AsyncClient(timeout=30.0),
            access_token=token,
            phone_number_id=phone_id,
            graph_version=os.environ.get("META_GRAPH_VERSION", "v20.0"),
        )
    return InMemoryGateway()


def _build_llm() -> LLMPort:
    """Pick the LLM port based on env. OpenRouter goes to real models via a
    routed-by-price aggregator; fall back to EchoLLM (deterministic stub) when
    no key is present so dev/CI/smoke runs don't need to wire anything.

    The model per call is :attr:`Tenant.model` — set at tenant creation or via
    PATCH /tenants/{id}. This function just picks WHICH provider answers; the
    tenant decides WHICH model gets requested."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if key:
        import httpx  # noqa: PLC0415

        return OpenRouterLLM(
            api_key=key,
            http=httpx.AsyncClient(timeout=30.0),
            referer="https://github.com/fmonfasani/waseller",
            title="Waseller",
        )
    return EchoLLM()


def _open_pg_connection() -> Any | None:  # noqa: ANN401 — DB-API connection is dynamic by design
    """Open one psycopg connection from ``WASELLER_POSTGRES_URL`` or return None.

    Strips the SQLAlchemy-style ``+psycopg`` dialect suffix the compose file uses
    so the raw URL is valid for ``psycopg.connect``. Returns None when the env
    var is unset (dev / CI / tests), letting callers fall back to InMemory."""
    url = os.environ.get("WASELLER_POSTGRES_URL", "").strip()
    if not url:
        return None
    if url.startswith("postgresql+psycopg://"):
        url = "postgresql://" + url[len("postgresql+psycopg://") :]
    elif url.startswith("postgresql+psycopg2://"):
        url = "postgresql://" + url[len("postgresql+psycopg2://") :]
    # psycopg is an optional dep (`pip install .[postgres]`); deferred so dev/CI
    # without it stays import-clean. The `type: ignore` is the standard escape
    # hatch for optional runtime deps under `mypy --strict`.
    import psycopg  # type: ignore[import-not-found]  # noqa: PLC0415

    return psycopg.connect(url, autocommit=False)


# One process-wide connection. Single-worker uvicorn means handlers serialize
# on the event loop and never share a sync cursor across coroutines; if/when
# we bump workers, each process opens its own connection.
_PG_CONNECTION: Any | None = _open_pg_connection()


def _build_repository() -> TenantRepositoryPort:
    """Pick tenant repo from env. Postgres when ``WASELLER_POSTGRES_URL`` is set
    (state survives container restarts and multi-worker setups); InMemory
    otherwise (dev / CI / tests). See ``infra/postgres/migrations/002_tenants.sql``."""
    if _PG_CONNECTION is not None:
        return PostgresTenantRepository(_PG_CONNECTION)
    return InMemoryTenantRepository()


def _build_hindsight() -> HindsightPort:
    """Pick the RAG store from env. Postgres tsvector when available so catalog
    facts survive restarts; in-memory substring search otherwise. Both adapters
    satisfy the same Protocol — no caller code changes."""
    if _PG_CONNECTION is not None:
        return PostgresHindsight(_PG_CONNECTION)
    return InMemoryHindsight()


def _build_buyer_memory() -> BuyerMemoryPort:
    """Pick buyer-memory backend from env. PostgresBuyerMemory when
    ``WASELLER_POSTGRES_URL`` is set (conversations survive restarts AND are
    visible across workers); InMemoryBuyerMemory otherwise (ephemeral). This
    is the last in-process state that prevented bumping ``uvicorn --workers``
    past 1 — see ``infra/docker/Dockerfile.api`` for the gating note."""
    if _PG_CONNECTION is not None:
        return PostgresBuyerMemory(_PG_CONNECTION)
    return InMemoryBuyerMemory()


def _build_templates() -> TemplateRepositoryPort:
    """Pick the template repo from env, same pattern as the others.
    Schema: ``infra/postgres/migrations/006_message_templates.sql``."""
    if _PG_CONNECTION is not None:
        return PostgresTemplateRepository(_PG_CONNECTION)
    return InMemoryTemplateRepository()


def _build_user_repo() -> UserRepositoryPort:
    if _PG_CONNECTION is not None:
        return PostgresUserRepository(_PG_CONNECTION)
    return InMemoryUserRepository()


def _build_session_repo() -> SessionRepositoryPort:
    if _PG_CONNECTION is not None:
        return PostgresSessionRepository(_PG_CONNECTION)
    return InMemorySessionRepository()


def _build_handoff_notifier() -> HandoffNotifierPort:
    """Pick the handoff notifier. HTTP by default — it no-ops anyway when no
    tenant has a ``webhook_url`` set. ``WASELLER_HANDOFF_NOTIFIER_DISABLED=1``
    forces the null adapter so tests + offline dev never hit the network."""
    if os.environ.get("WASELLER_HANDOFF_NOTIFIER_DISABLED", "").strip() == "1":
        return NullHandoffNotifier()
    import httpx  # noqa: PLC0415

    return HttpHandoffNotifier(client=httpx.AsyncClient(timeout=5.0))


def _build_bot_pauses() -> BotPausePort:
    """Pick the bot-pause backend. Postgres in prod (state survives api
    restarts and is visible across workers), InMemory in dev/CI/tests."""
    if _PG_CONNECTION is not None:
        return PostgresBotPauseRepository(_PG_CONNECTION)
    return InMemoryBotPauseRepository()


_auth_service = AuthService(
    users=_build_user_repo(),
    sessions=_build_session_repo(),
)

# Cookie name; settable via env for multi-deploy setups but defaults are fine.
_AUTH_COOKIE = os.environ.get("WASELLER_AUTH_COOKIE", "wapsell_session")


def _auth_cookie_secure() -> bool:
    """`secure=True` is the prod default — browsers drop the cookie on plain
    HTTP. http://localhost dev + the test suite (TestClient runs on http) need
    it false. Read at request time so a test can monkeypatch the env without
    restarting the api process."""
    return os.environ.get("WASELLER_AUTH_COOKIE_SECURE", "true").lower() != "false"


# Cookie SameSite policy. Default ``strict`` is the most restrictive and the
# right choice when the dashboard and the API live on the same origin (e.g.
# wapsell.com hosting both). When the dashboard is on a different origin
# (e.g. local dev at localhost:3000 talking to https://pipaas.com, or a
# subdomain dashboard.example.com talking to api.example.com), the browser
# refuses to send Strict cookies on the cross-site /auth/me requests and the
# user gets booted to /login. Operators flip this to ``none`` (which requires
# Secure=true, already on by default) for those deployments.
def _auth_cookie_samesite() -> str:
    raw = os.environ.get("WASELLER_AUTH_COOKIE_SAMESITE", "strict").lower()
    if raw not in {"strict", "lax", "none"}:
        # Silently fall back rather than 5xx on a typo — the cookie still
        # gets set, just with the safer default.
        return "strict"
    return raw


# --- Access control (PR #27) -----------------------------------------------
# Two-stage rollout. Default ``WASELLER_AUTH_REQUIRED=false`` keeps the API
# fully open so existing deploys (and the bootstrap admin script) don't break
# the day this code merges. Operators flip the flag to "true" after they have
# created the first admin user and onboarded their tenants, at which point:
#   * ADMIN — sees and can touch any tenant; creates tenants and users.
#   * TENANT — sees and can touch only their own tenant (user.tenant_id).
#   * No session — every protected route returns 401.
# When the flag is "false", the helpers below are silent no-ops and the API
# behaves exactly as it did before this PR.


def _auth_required() -> bool:
    return os.environ.get("WASELLER_AUTH_REQUIRED", "").strip().lower() == "true"


def _optional_current_user(request: Request) -> User | None:
    """Resolve the cookie-bound session to a :class:`User`, or ``None`` when
    there is no cookie or the session is expired / unknown. Never raises —
    callers decide whether a missing user should 401 or pass through."""
    token = request.cookies.get(_AUTH_COOKIE)
    if not token:
        return None
    try:
        return _auth_service.authenticate(token)
    except AuthError:
        return None


def _assert_authenticated(request: Request) -> User | None:
    """Enforce that *some* valid session exists. No-op when auth is disabled.
    Returns the user so callers can keep going without a second lookup."""
    if not _auth_required():
        return _optional_current_user(request)
    user = _optional_current_user(request)
    if user is None:
        raise HTTPException(status_code=401, detail="authentication required")
    return user


def _assert_admin(request: Request) -> User | None:
    """Require ADMIN role. No-op when auth is disabled so the bootstrap
    admin script + existing tooling keep working pre-flip."""
    if not _auth_required():
        return _optional_current_user(request)
    user = _assert_authenticated(request)
    if user is None or user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="admin role required")
    return user


def _assert_tenant_access(request: Request, tenant_id: str) -> User | None:
    """Require the caller to either be ADMIN or to own ``tenant_id``. No-op
    when auth is disabled. 401 for missing session, 403 for cross-tenant
    peeking — the distinction matters for the dashboard's redirect logic."""
    if not _auth_required():
        return _optional_current_user(request)
    user = _assert_authenticated(request)
    if user is None:
        # _assert_authenticated already raised, but mypy can't see that.
        raise HTTPException(status_code=401, detail="authentication required")
    if user.role == UserRole.ADMIN:
        return user
    if user.tenant_id != tenant_id:
        raise HTTPException(status_code=403, detail="tenant access denied")
    return user


def _filter_visible_tenants(request: Request, tenants: list[Tenant]) -> list[Tenant]:
    """Scope the /tenants listing to what the caller is allowed to see.
    ADMIN sees every tenant; TENANT sees only their own. When auth is
    disabled, returns the input unchanged."""
    if not _auth_required():
        return tenants
    user = _optional_current_user(request)
    if user is None:
        # /tenants listing demands a session when auth is on.
        raise HTTPException(status_code=401, detail="authentication required")
    if user.role == UserRole.ADMIN:
        return tenants
    return [t for t in tenants if t.id == user.tenant_id]


app = FastAPI(title="Waseller API", version="0.15.0")
_client = WasellerClient(
    repository=_build_repository(),
    hindsight=_build_hindsight(),
    memory=_build_buyer_memory(),
    gateway=_build_gateway(),
    llm=_build_llm(),
    templates=_build_templates(),
    handoff_notifier=_build_handoff_notifier(),
    bot_pauses=_build_bot_pauses(),
)

# --- Rate limiting (SlowAPI) -----------------------------------------------
# Per-IP by default; in prod behind nginx the X-Forwarded-For chain is honored
# by get_remote_address as long as `proxy_headers=True` is set on uvicorn (see
# infra/scripts/deploy.sh). Storage is in-memory — for multi-process we'd swap
# in a Redis backend (memory:// → redis://...).
_RATE_DEFAULT = os.environ.get("WASELLER_RATE_LIMIT_DEFAULT", "120/minute")
_RATE_WEBHOOK = os.environ.get("WASELLER_RATE_LIMIT_WEBHOOK", "600/minute")
_RATE_ONBOARD = os.environ.get("WASELLER_RATE_LIMIT_ONBOARD", "30/minute")
limiter = Limiter(
    key_func=get_remote_address,
    default_limits=[_RATE_DEFAULT],
    storage_uri=os.environ.get("WASELLER_RATE_LIMIT_STORAGE", "memory://"),
)
app.state.limiter = limiter
# SlowAPI's handler is typed for its specific exception subclass; Starlette's
# add_exception_handler is typed for `Exception`. The runtime call is correct
# and this is the documented integration pattern.
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]

# CORS for the admin dashboard. Defaults cover:
#   * localhost dev on a few common Next.js ports — Next.js auto-increments
#     past 3000 when it's busy, so we whitelist a small range to avoid the
#     "Next picked 3002 and CORS broke" gotcha we hit on PR #29.
#   * The production dashboard at https://app.wapsell.com (PR #34).
# Operators override the whole list via WASELLER_DASHBOARD_ORIGINS
# (comma-separated). When auth enforcement is on, the API still demands a
# valid session — CORS only decides which origins are allowed to *try*.
_default_origins = ",".join(
    [
        "http://localhost:3000",
        "http://localhost:3001",
        "http://localhost:3002",
        "http://localhost:3003",
        "http://127.0.0.1:3000",
        "http://127.0.0.1:3001",
        "http://127.0.0.1:3002",
        "http://127.0.0.1:3003",
        "https://app.wapsell.com",
    ]
)
_origins = [
    o.strip()
    for o in os.environ.get("WASELLER_DASHBOARD_ORIGINS", _default_origins).split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class GoalRequest(BaseModel):
    tenant_id: str = "default"
    goal_type: str = "qualify"
    message: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class SkillRequest(BaseModel):
    skill: str
    context: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


class TenantCreate(BaseModel):
    name: str
    slug: str
    model: str | None = None
    whatsapp_phone_number_id: str | None = None


class TenantUpdate(BaseModel):
    model: str | None = None
    whatsapp_phone_number_id: str | None = None


class OnboardingRequest(BaseModel):
    """Normalized Meta Embedded Signup callback. The router strips Meta's
    vendor envelope; the flow stays agnostic of payload shape."""

    phone_number_id: str
    business_name: str
    waba_id: str | None = None
    business_id: str | None = None


class OnboardingResponse(BaseModel):
    tenant_id: str
    slug: str
    is_new: bool  # False = idempotent replay (Meta retries on non-2xx)


class TenantOut(BaseModel):
    """Tenant projection for the API — flattens the enum + isoformats the date."""

    id: str
    name: str
    slug: str
    status: str
    model: str
    whatsapp_phone_number_id: str | None
    created_at: str

    @classmethod
    def from_tenant(cls, t: Tenant) -> TenantOut:
        return cls(
            id=t.id,
            name=t.name,
            slug=t.slug,
            status=t.status.value,
            model=t.model,
            whatsapp_phone_number_id=t.whatsapp_phone_number_id,
            created_at=t.created_at.isoformat(),
        )


class CatalogFactIn(BaseModel):
    """One row of the inbound catalog payload. `content` is the free-text
    description the agent will retrieve via RAG; `metadata` is opaque kv tags
    (sku, category, price_cents...) for downstream filtering."""

    content: str
    metadata: dict[str, str] = Field(default_factory=dict)


class CatalogIngestRequest(BaseModel):
    """Bulk upload — N facts per call. `source` labels the batch so multiple
    uploads (csv-v1, manual-2026-06, ...) are distinguishable in audit later."""

    source: str = "manual-ingest"
    facts: list[CatalogFactIn]


class CatalogIngestResponse(BaseModel):
    tenant_id: str
    ingested: int
    fact_ids: list[str]


class CatalogFactOut(BaseModel):
    id: str
    source: str
    content: str
    metadata: dict[str, str]
    created_at: str


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "waseller-api"}


_HEALTH_HTTP_OK = 200


def _check_postgres() -> dict[str, str]:
    """Trivial SELECT against the shared connection. Surfaces dead connections
    after network blips or postgres restarts."""
    if _PG_CONNECTION is None:
        return {"status": "skipped", "detail": "WASELLER_POSTGRES_URL not set"}
    try:
        with _PG_CONNECTION.cursor() as cur:
            cur.execute("SELECT 1")
            cur.fetchall()
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:200]}
    return {"status": "ok"}


async def _check_openrouter() -> dict[str, str]:
    """List models is cheap and validates auth without spending inference credits."""
    key = os.environ.get("OPENROUTER_API_KEY", "").strip()
    if not key:
        return {"status": "skipped", "detail": "OPENROUTER_API_KEY not set"}
    import httpx  # noqa: PLC0415

    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                "https://openrouter.ai/api/v1/models",
                headers={"Authorization": f"Bearer {key}"},
            )
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:200]}
    if res.status_code != _HEALTH_HTTP_OK:
        return {"status": "error", "detail": f"http {res.status_code}"}
    return {"status": "ok"}


async def _check_meta() -> dict[str, str]:
    """Fetch the configured phone-number — same endpoint smoke-webhook.sh uses
    to validate the token + recipient registration on the WhatsApp side."""
    phone_id = os.environ.get("META_PHONE_NUMBER_ID", "").strip()
    token = os.environ.get("META_ACCESS_TOKEN", "").strip()
    if not (phone_id and token):
        return {
            "status": "skipped",
            "detail": "META_ACCESS_TOKEN/PHONE_NUMBER_ID missing",
        }
    import httpx  # noqa: PLC0415

    graph_version = os.environ.get("META_GRAPH_VERSION", "v20.0")
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            res = await client.get(
                f"https://graph.facebook.com/{graph_version}/{phone_id}",
                params={"fields": "display_phone_number,verified_name"},
                headers={"Authorization": f"Bearer {token}"},
            )
    except Exception as exc:
        return {"status": "error", "detail": str(exc)[:200]}
    if res.status_code != _HEALTH_HTTP_OK:
        return {"status": "error", "detail": f"http {res.status_code}"}
    return {"status": "ok"}


@app.get("/health/deep")
async def health_deep() -> Response:
    """Probe each external dependency and report status individually.

    Designed for monitoring + post-deploy validation, not the docker
    healthcheck (which uses ``/health`` and must stay cheap). Returns 200 with
    ``status: ok`` if all probes pass, 503 with ``status: degraded`` if any
    fails. Failing probes still return a per-dependency error string so the
    response is the single source of truth for which dep is down.
    """
    checks: dict[str, dict[str, str]] = {
        "postgres": _check_postgres(),
        "openrouter": await _check_openrouter(),
        "meta": await _check_meta(),
    }
    degraded = any(c["status"] == "error" for c in checks.values())
    payload: dict[str, Any] = {
        "status": "degraded" if degraded else "ok",
        "service": "waseller-api",
        "checks": checks,
    }
    # 503 so external monitors page on actual breakage instead of just parsing
    # the body; 200 for the happy path.
    return JSONResponse(
        status_code=503 if degraded else _HEALTH_HTTP_OK,
        content=payload,
    )


# --- Tenants (admin) -------------------------------------------------------


@app.get("/tenants", response_model=list[TenantOut])
async def list_tenants(request: Request) -> list[TenantOut]:
    tenants = _client.tenants.list()
    return [TenantOut.from_tenant(t) for t in _filter_visible_tenants(request, tenants)]


@app.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(req: TenantCreate, request: Request) -> TenantOut:
    _assert_admin(request)
    try:
        tenant = _client.create_tenant(req.name, req.slug, model=req.model)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if req.whatsapp_phone_number_id:
        tenant = _client.tenants.repository.update(
            tenant.model_copy(update={"whatsapp_phone_number_id": req.whatsapp_phone_number_id})
        )
    return TenantOut.from_tenant(tenant)


@app.get("/tenants/{tenant_id}", response_model=TenantOut)
async def get_tenant(tenant_id: str, request: Request) -> TenantOut:
    _assert_tenant_access(request, tenant_id)
    try:
        return TenantOut.from_tenant(_client.tenants.get(tenant_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc


@app.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def update_tenant(tenant_id: str, req: TenantUpdate, request: Request) -> TenantOut:
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    updates: dict[str, Any] = {}
    if req.model is not None:
        updates["model"] = req.model
    if req.whatsapp_phone_number_id is not None:
        updates["whatsapp_phone_number_id"] = req.whatsapp_phone_number_id
    if updates:
        tenant = _client.tenants.repository.update(tenant.model_copy(update=updates))
    return TenantOut.from_tenant(tenant)


@app.post("/tenants/connect-whatsapp", response_model=OnboardingResponse, status_code=201)
@limiter.limit(_RATE_ONBOARD)
async def connect_whatsapp(request: Request, req: OnboardingRequest) -> OnboardingResponse:
    """Meta Embedded Signup callback → provision a tenant.

    Idempotent on ``phone_number_id`` (returns 201 either way; the body's
    ``is_new`` discriminates fresh vs. replay so dashboards don't mislead).
    """
    _assert_admin(request)
    try:
        result = await _client.onboarding.run(
            MetaSignupPayload(
                phone_number_id=req.phone_number_id,
                business_name=req.business_name,
                waba_id=req.waba_id,
                business_id=req.business_id,
            )
        )
    except OnboardingError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return OnboardingResponse(
        tenant_id=result.tenant.id, slug=result.tenant.slug, is_new=result.is_new
    )


class SoulOut(BaseModel):
    """Response shape for /tenants/{id}/soul. Bundles the rendered prompt
    (what the agent actually sees) with the persisted config (what the
    dashboard form needs to pre-fill its inputs)."""

    soul: str
    config: SoulConfig


@app.get("/tenants/{tenant_id}/soul", response_model=SoulOut)
async def get_tenant_soul(tenant_id: str, request: Request) -> SoulOut:
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return SoulOut(
        soul=_client.soul_for(tenant_id),
        config=tenant.soul_config or SoulConfig(),
    )


@app.put("/tenants/{tenant_id}/soul", response_model=SoulOut)
async def update_tenant_soul(tenant_id: str, req: SoulConfig, request: Request) -> SoulOut:
    """Persist a per-tenant SOUL configuration and return the freshly-rendered
    prompt. Body is the full :class:`SoulConfig` (Pydantic) — partial updates
    aren't supported because the SOUL is small enough that a full overwrite is
    safer than reconciling a diff."""
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    updated = tenant.model_copy(update={"soul_config": req})
    _client.tenants.repository.update(updated)
    return SoulOut(
        soul=_client.soul_for(tenant_id),
        config=req,
    )


# --- Handoff (bot → human) -------------------------------------------------


class HandoffOut(BaseModel):
    """Response shape for /tenants/{id}/handoff. Mirrors the SoulOut pattern:
    one endpoint returns both the persisted config (for the dashboard form to
    pre-fill) and any derived state the UI would otherwise compute itself."""

    config: HandoffConfig


@app.get("/tenants/{tenant_id}/handoff", response_model=HandoffOut)
async def get_tenant_handoff(tenant_id: str, request: Request) -> HandoffOut:
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    return HandoffOut(config=tenant.handoff_config or HandoffConfig())


@app.put("/tenants/{tenant_id}/handoff", response_model=HandoffOut)
async def update_tenant_handoff(tenant_id: str, req: HandoffConfig, request: Request) -> HandoffOut:
    """Persist a per-tenant handoff configuration. Body is the full
    :class:`HandoffConfig` — partial updates aren't supported because the
    config is small and overwrite is safer than reconciling a diff. Setting
    ``enabled=false`` is how a customer disables handoff without losing
    their keyword list."""
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    updated = tenant.model_copy(update={"handoff_config": req})
    _client.tenants.repository.update(updated)
    return HandoffOut(config=req)


# --- Catalog ingest (Hindsight RAG) ----------------------------------------


@app.post(
    "/tenants/{tenant_id}/catalog/facts",
    response_model=CatalogIngestResponse,
    status_code=201,
)
async def ingest_catalog_facts(
    tenant_id: str, req: CatalogIngestRequest, request: Request
) -> CatalogIngestResponse:
    """Append facts to the tenant's Hindsight RAG store.

    The agent picks these up at runtime via the catalog-lookup skill and the
    RAG step of ``AgentLoop.respond``. Facts are append-only — to "update" a
    price, POST a new fact; the freshest match wins via Postgres's tsvector
    ranking + ``created_at`` tiebreak. Backend is whichever Hindsight adapter
    the composition root picked (Postgres in prod when ``WASELLER_POSTGRES_URL``
    is set, in-memory otherwise)."""
    _assert_tenant_access(request, tenant_id)
    try:
        _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    if not req.facts:
        raise HTTPException(status_code=422, detail="facts must not be empty")
    facts = [
        Fact(tenant_id=tenant_id, source=req.source, content=f.content, metadata=f.metadata)
        for f in req.facts
    ]
    for f in facts:
        _client.hindsight.add_fact(f)
    return CatalogIngestResponse(
        tenant_id=tenant_id,
        ingested=len(facts),
        fact_ids=[f.id for f in facts],
    )


class ConversationThreadOut(BaseModel):
    """Row in the dashboard's conversations inbox. `from_number` is parsed
    out of the buyer_id (`slug:from_number` by convention) so the dashboard
    can show "Cliente +54..." without having to know the encoding.

    ``bot_paused`` / ``bot_paused_until`` reflect the bot-pause registry —
    when truthy, the agent skips generating replies and the dashboard shows
    a "tomado por humano" badge."""

    buyer_id: str
    from_number: str
    message_count: int
    last_at: str
    last_text: str
    bot_paused: bool = False
    bot_paused_until: str | None = None


class ConversationTurnOut(BaseModel):
    """One row of the conversation thread view. Mirrors BuyerInteraction
    but with at as an ISO string + metadata always present (defaults to {})."""

    role: str
    text: str
    at: str
    metadata: dict[str, str]


class ConversationThreadDetailOut(BaseModel):
    """Detail view shape — turns plus the pause state for *this* buyer.
    Bundled into one response so the thread page doesn't need a second
    request to render the takeover banner."""

    turns: list[ConversationTurnOut]
    bot_paused: bool = False
    bot_paused_until: str | None = None


class SendMessageRequest(BaseModel):
    """Body for POST /conversations/{buyer_id}/send. ``pause_hours`` lets the
    human extend the pause window in the same call — typical UX: type a reply,
    hit send, bot stays muted for 8h while the human stays in control."""

    text: str
    pause_hours: int | None = 8


class PauseRequest(BaseModel):
    """Body for POST /conversations/{buyer_id}/pause."""

    hours: int = 8


@app.get(
    "/tenants/{tenant_id}/conversations",
    response_model=list[ConversationThreadOut],
)
async def list_conversations(tenant_id: str, request: Request) -> list[ConversationThreadOut]:
    """Inbox-style listing of every buyer that has ever messaged this tenant.
    Most recently active first. Backs the dashboard /conversations page."""
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc

    # buyer_ids are composed `tenant.slug:from_number` (see waseller.client.buyer_id_for)
    # so filtering by `slug:` prefix isolates this tenant's threads.
    threads = await _client.memory.list_threads(prefix=f"{tenant.slug}:")
    # Pre-load active pauses once so the per-thread badge resolves in O(1)
    # instead of one is_paused() round-trip per row.
    paused_by_bid = {p.buyer_id: p for p in _client.bot_pauses.list_active(tenant.id)}
    return [
        ConversationThreadOut(
            buyer_id=t.buyer_id,
            from_number=_split_from_number(t.buyer_id),
            message_count=t.message_count,
            last_at=t.last_at.isoformat(),
            last_text=t.last_text,
            bot_paused=t.buyer_id in paused_by_bid,
            bot_paused_until=(
                paused_by_bid[t.buyer_id].paused_until.isoformat()
                if t.buyer_id in paused_by_bid
                else None
            ),
        )
        for t in threads
    ]


@app.get(
    "/tenants/{tenant_id}/conversations/{buyer_id}",
    response_model=ConversationThreadDetailOut,
)
async def get_conversation_thread(
    tenant_id: str, buyer_id: str, request: Request
) -> ConversationThreadDetailOut:
    """Full chronological transcript + pause state for one buyer. Limit
    defaults to the adapter cap (50 turns) which is enough for sales
    conversations that rarely run longer than ~20 turns. Bundling the pause
    state here saves the dashboard a second round-trip on every page load."""
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    # Guard against cross-tenant peeking: a buyer_id from tenant A must not
    # leak into tenant B's transcript view.
    if not buyer_id.startswith(f"{tenant.slug}:"):
        raise HTTPException(status_code=404, detail="conversation not found")

    turns = await _client.memory.recall(buyer_id)
    pause = _client.bot_pauses.get(tenant.id, buyer_id)
    now = datetime.now(UTC)
    active_pause = pause if (pause is not None and pause.paused_until > now) else None
    return ConversationThreadDetailOut(
        turns=[
            ConversationTurnOut(
                role=str(t.role),
                text=t.text,
                at=t.at.isoformat(),
                metadata=dict(t.metadata),
            )
            for t in turns
        ],
        bot_paused=active_pause is not None,
        bot_paused_until=active_pause.paused_until.isoformat() if active_pause else None,
    )


# --- Inbox: human takeover (send / pause / resume) -------------------------


def _tenant_for_conv(tenant_id: str, buyer_id: str) -> Tenant:
    """Resolve + cross-tenant guard for the inbox actions. The buyer_id
    convention is ``slug:from_number``; rejecting on prefix mismatch keeps
    a tenant_id-buyer_id mix-up from leaking a thread into the wrong shop."""
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    if not buyer_id.startswith(f"{tenant.slug}:"):
        raise HTTPException(status_code=404, detail="conversation not found")
    return tenant


@app.post(
    "/tenants/{tenant_id}/conversations/{buyer_id}/send",
    response_model=ConversationTurnOut,
    status_code=201,
)
async def send_human_message(
    tenant_id: str, buyer_id: str, req: SendMessageRequest, request: Request
) -> ConversationTurnOut:
    """Send a human-authored reply to the buyer and persist it as a turn.

    Sending implicitly pauses the bot (default 8h) so it doesn't talk over
    the human. Set ``pause_hours=0`` to send without pausing — useful when
    the human just wants to drop in a one-off message and let the bot keep
    handling the rest of the conversation."""
    _assert_tenant_access(request, tenant_id)
    tenant = _tenant_for_conv(tenant_id, buyer_id)
    text = req.text.strip()
    if not text:
        raise HTTPException(status_code=422, detail="text must not be empty")

    from_number = _split_from_number(buyer_id)
    vendor_message_id = ""
    delivery_error: str | None = None
    try:
        sent = await _client.gateway.send_text(
            to_number=from_number, text=text, tenant_id=tenant.id
        )
        vendor_message_id = sent.vendor_message_id or ""
    except Exception as exc:
        # Mirror the webhook handler: persist the human turn even when the
        # gateway fails so the dashboard shows what was attempted, with the
        # error captured for triage.
        delivery_error = str(exc)[:200]
        _webhook_log.warning("human send_text failed for %s: %s", buyer_id, delivery_error)

    metadata: dict[str, str] = {"human": "true"}
    if vendor_message_id:
        metadata["vendor_message_id"] = vendor_message_id
    if delivery_error:
        metadata["delivery_error"] = delivery_error

    # Pause the bot so it doesn't immediately reply on top of the human.
    # pause_hours=0 means "send but keep bot active" — opt-out for power users.
    if req.pause_hours and req.pause_hours > 0:
        try:
            until = datetime.now(UTC) + timedelta(hours=req.pause_hours)
            _client.bot_pauses.pause(tenant.id, buyer_id, until)
            metadata["bot_paused_until"] = until.isoformat()
        except Exception as exc:
            _webhook_log.warning("bot pause after send failed for %s: %s", buyer_id, str(exc)[:200])

    try:
        await _client.memory.remember(
            buyer_id,
            BuyerInteraction(text=text, role="agent", metadata=metadata),
        )
    except Exception as exc:
        _webhook_log.warning("human turn remember failed for %s: %s", buyer_id, str(exc)[:200])

    return ConversationTurnOut(
        role="agent",
        text=text,
        at=datetime.now(UTC).isoformat(),
        metadata=metadata,
    )


class PauseStateOut(BaseModel):
    bot_paused: bool
    bot_paused_until: str | None = None


@app.post(
    "/tenants/{tenant_id}/conversations/{buyer_id}/pause",
    response_model=PauseStateOut,
)
async def pause_bot(
    tenant_id: str, buyer_id: str, req: PauseRequest, request: Request
) -> PauseStateOut:
    """Mute the bot for this buyer. ``hours <= 0`` is rejected to avoid a
    silent no-op when a UI accidentally sends 0."""
    _assert_tenant_access(request, tenant_id)
    tenant = _tenant_for_conv(tenant_id, buyer_id)
    if req.hours <= 0:
        raise HTTPException(status_code=422, detail="hours must be > 0")
    until = datetime.now(UTC) + timedelta(hours=req.hours)
    _client.bot_pauses.pause(tenant.id, buyer_id, until)
    return PauseStateOut(bot_paused=True, bot_paused_until=until.isoformat())


@app.post(
    "/tenants/{tenant_id}/conversations/{buyer_id}/resume",
    response_model=PauseStateOut,
)
async def resume_bot(tenant_id: str, buyer_id: str, request: Request) -> PauseStateOut:
    """Resume the bot for this buyer — next inbound message gets a normal
    LLM-generated reply. Idempotent: resuming an already-active buyer is a
    no-op."""
    _assert_tenant_access(request, tenant_id)
    tenant = _tenant_for_conv(tenant_id, buyer_id)
    _client.bot_pauses.resume(tenant.id, buyer_id)
    return PauseStateOut(bot_paused=False, bot_paused_until=None)


def _split_from_number(buyer_id: str) -> str:
    """Pull the `from_number` portion out of a `slug:from_number` buyer_id.
    Returns the original string when the colon convention isn't met so an
    unexpected adapter never blank-erases the dashboard row."""
    _, sep, rest = buyer_id.partition(":")
    return rest if sep else buyer_id


# --- Analytics (PR #28) ----------------------------------------------------
# A small set of headline KPIs the dashboard needs to look like a real product
# instead of a chat viewer: volume, hot leads, handoff rate, response time,
# and a daily trend for the chart. Computed by iterating the existing buyer
# memory; cheap enough for tenants in the demo / first-customer range, and
# trivially swappable for a dedicated analytics service later.


class DailyBucket(BaseModel):
    date: str  # YYYY-MM-DD (UTC).
    buyer: int
    agent: int


class HandoffKeywordRow(BaseModel):
    keyword: str
    count: int


class AnalyticsOut(BaseModel):
    """Headline KPIs for one tenant over a sliding window. Anything that
    requires a chart on the dashboard is bundled here so the page renders
    from a single request."""

    window_days: int
    window_start: str
    window_end: str
    messages_total: int
    messages_buyer: int
    messages_agent: int
    unique_buyers: int
    handoff_count: int
    handoff_rate: float
    human_takeover_count: int
    # Median seconds from a buyer turn to the next agent turn in the same
    # thread. Null when there isn't a single completed buyer→agent pair in
    # the window — usually fresh tenants with no traffic yet.
    median_response_seconds: float | None
    daily: list[DailyBucket]
    top_handoff_keywords: list[HandoffKeywordRow]


_ANALYTICS_DEFAULT_DAYS = 30
_ANALYTICS_MAX_DAYS = 365


@app.get("/tenants/{tenant_id}/analytics", response_model=AnalyticsOut)
async def get_analytics(
    tenant_id: str, request: Request, days: int = _ANALYTICS_DEFAULT_DAYS
) -> AnalyticsOut:
    """Compute KPIs for the last ``days`` days. Default 30, max 365 — beyond
    a year the in-memory aggregation gets expensive and you want a dedicated
    OLAP store anyway."""
    _assert_tenant_access(request, tenant_id)
    try:
        tenant = _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    if days <= 0 or days > _ANALYTICS_MAX_DAYS:
        raise HTTPException(
            status_code=422,
            detail=f"days must be between 1 and {_ANALYTICS_MAX_DAYS}",
        )

    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    threads = await _client.memory.list_threads(prefix=f"{tenant.slug}:")
    daily_buyer: dict[str, int] = {}
    daily_agent: dict[str, int] = {}
    messages_buyer = 0
    messages_agent = 0
    handoff_count = 0
    human_takeover_count = 0
    handoff_keywords: dict[str, int] = {}
    response_seconds: list[float] = []
    unique_buyers_in_window: set[str] = set()

    for thread in threads:
        turns = await _client.memory.recall(thread.buyer_id)
        last_buyer_at: datetime | None = None
        for turn in turns:
            if turn.at < since:
                # The recall is chronological — we could break early, but the
                # turn list is typically <50 entries so the early-out doesn't
                # pay off readability.
                continue
            unique_buyers_in_window.add(thread.buyer_id)
            day = turn.at.strftime("%Y-%m-%d")
            if turn.role == "buyer":
                messages_buyer += 1
                daily_buyer[day] = daily_buyer.get(day, 0) + 1
                last_buyer_at = turn.at
            else:
                messages_agent += 1
                daily_agent[day] = daily_agent.get(day, 0) + 1
                if turn.metadata.get("handoff") == "true":
                    handoff_count += 1
                    kw = turn.metadata.get("handoff_keyword")
                    if kw:
                        handoff_keywords[kw] = handoff_keywords.get(kw, 0) + 1
                if turn.metadata.get("human") == "true":
                    human_takeover_count += 1
                if last_buyer_at is not None:
                    response_seconds.append((turn.at - last_buyer_at).total_seconds())
                    last_buyer_at = None  # one agent reply per buyer prompt counts

    messages_total = messages_buyer + messages_agent
    handoff_rate = (handoff_count / messages_agent) if messages_agent > 0 else 0.0

    # Build a dense daily series so the chart renders zero-buckets instead of
    # a gappy axis. Always end at "today UTC" so the right edge is stable.
    daily = []
    for i in range(days):
        d = (since + timedelta(days=i)).strftime("%Y-%m-%d")
        daily.append(
            DailyBucket(
                date=d,
                buyer=daily_buyer.get(d, 0),
                agent=daily_agent.get(d, 0),
            )
        )

    # Sort tuples instead of dicts so mypy can see the key as int rather than
    # falling back to object — the sort comparison would otherwise be untyped.
    top_kw_tuples: list[tuple[str, int]] = sorted(
        handoff_keywords.items(), key=lambda r: r[1], reverse=True
    )[:5]

    return AnalyticsOut(
        window_days=days,
        window_start=since.isoformat(),
        window_end=now.isoformat(),
        messages_total=messages_total,
        messages_buyer=messages_buyer,
        messages_agent=messages_agent,
        unique_buyers=len(unique_buyers_in_window),
        handoff_count=handoff_count,
        handoff_rate=handoff_rate,
        human_takeover_count=human_takeover_count,
        median_response_seconds=_median(response_seconds),
        daily=daily,
        top_handoff_keywords=[
            HandoffKeywordRow(keyword=kw, count=count) for kw, count in top_kw_tuples
        ],
    )


def _median(values: list[float]) -> float | None:
    """Median of a (possibly empty) list. ``None`` for empty so the dashboard
    can show "—" instead of pretending the answer is 0."""
    if not values:
        return None
    sorted_v = sorted(values)
    mid = len(sorted_v) // 2
    if len(sorted_v) % 2 == 1:
        return sorted_v[mid]
    return (sorted_v[mid - 1] + sorted_v[mid]) / 2


# --- Message templates (WhatsApp Business) ---------------------------------


class TemplateCreate(BaseModel):
    """Body for POST /tenants/{id}/templates. The status starts at DRAFT
    server-side — the dashboard moves it through SUBMITTED → APPROVED with
    the PATCH endpoint."""

    name: str
    body: str
    language: str = "es_AR"
    category: TemplateCategory = TemplateCategory.UTILITY


class TemplateUpdate(BaseModel):
    """Body for PATCH /tenants/{id}/templates/{template_id}. All fields
    optional — partial updates supported because a status flip + a rejection
    reason often arrive together but never with a body edit (a body edit
    after submission requires a new submission to Meta anyway)."""

    name: str | None = None
    body: str | None = None
    language: str | None = None
    category: TemplateCategory | None = None
    status: TemplateStatus | None = None
    vendor_template_id: str | None = None
    rejection_reason: str | None = None


class TemplateOut(BaseModel):
    """Wire shape. ISO-string timestamps so the dashboard reads them
    straight off the JSON without timezone gymnastics."""

    id: str
    tenant_id: str
    name: str
    language: str
    category: TemplateCategory
    body: str
    status: TemplateStatus
    vendor_template_id: str | None
    rejection_reason: str | None
    created_at: str
    submitted_at: str | None
    approved_at: str | None

    @classmethod
    def from_template(cls, t: MessageTemplate) -> TemplateOut:
        return cls(
            id=t.id,
            tenant_id=t.tenant_id,
            name=t.name,
            language=t.language,
            category=t.category,
            body=t.body,
            status=t.status,
            vendor_template_id=t.vendor_template_id,
            rejection_reason=t.rejection_reason,
            created_at=t.created_at.isoformat(),
            submitted_at=t.submitted_at.isoformat() if t.submitted_at else None,
            approved_at=t.approved_at.isoformat() if t.approved_at else None,
        )


@app.get(
    "/tenants/{tenant_id}/templates",
    response_model=list[TemplateOut],
)
async def list_templates(tenant_id: str, request: Request) -> list[TemplateOut]:
    _assert_tenant_access(request, tenant_id)
    try:
        _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    templates = _client.templates.list_for(tenant_id)
    return [TemplateOut.from_template(t) for t in templates]


@app.post(
    "/tenants/{tenant_id}/templates",
    response_model=TemplateOut,
    status_code=201,
)
async def create_template(tenant_id: str, req: TemplateCreate, request: Request) -> TemplateOut:
    _assert_tenant_access(request, tenant_id)
    try:
        _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    template = MessageTemplate(
        tenant_id=tenant_id,
        name=req.name,
        body=req.body,
        language=req.language,
        category=req.category,
    )
    try:
        saved = _client.templates.add(template)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return TemplateOut.from_template(saved)


@app.patch(
    "/tenants/{tenant_id}/templates/{template_id}",
    response_model=TemplateOut,
)
async def update_template(
    tenant_id: str, template_id: str, req: TemplateUpdate, request: Request
) -> TemplateOut:
    _assert_tenant_access(request, tenant_id)
    template = _client.templates.get(template_id)
    if template is None or template.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="template not found")

    # Build the patch dict explicitly so unset fields don't accidentally clear
    # the persisted column (model_dump(exclude_unset=True) misses None which
    # is a valid value for nullable columns like vendor_template_id).
    patch: dict[str, Any] = {}
    if req.name is not None:
        patch["name"] = req.name
    if req.body is not None:
        patch["body"] = req.body
    if req.language is not None:
        patch["language"] = req.language
    if req.category is not None:
        patch["category"] = req.category
    if req.status is not None:
        patch["status"] = req.status
        # Auto-stamp the lifecycle timestamps when status flips. The dashboard
        # therefore doesn't have to send them explicitly.
        if req.status == TemplateStatus.SUBMITTED and template.submitted_at is None:
            patch["submitted_at"] = datetime.now(UTC)
        if req.status == TemplateStatus.APPROVED and template.approved_at is None:
            patch["approved_at"] = datetime.now(UTC)
    if req.vendor_template_id is not None:
        patch["vendor_template_id"] = req.vendor_template_id
    if req.rejection_reason is not None:
        patch["rejection_reason"] = req.rejection_reason

    updated = template.model_copy(update=patch)
    saved = _client.templates.update(updated)
    return TemplateOut.from_template(saved)


@app.delete(
    "/tenants/{tenant_id}/templates/{template_id}",
    status_code=204,
)
async def delete_template(tenant_id: str, template_id: str, request: Request) -> Response:
    _assert_tenant_access(request, tenant_id)
    template = _client.templates.get(template_id)
    if template is None or template.tenant_id != tenant_id:
        raise HTTPException(status_code=404, detail="template not found")
    _client.templates.delete(template_id)
    return Response(status_code=204)


# --- Auth (dashboard login / register / me / logout) ----------------------


class LoginRequest(BaseModel):
    email: str
    password: str


class RegisterRequest(BaseModel):
    """Admin-only payload to create a new user. Surfaced by the dashboard's
    'invite team member' flow; the API caller must be authenticated as ADMIN
    (enforced when auth becomes mandatory in a later PR)."""

    email: str
    password: str
    role: UserRole = UserRole.TENANT
    tenant_id: str | None = None


class UserOut(BaseModel):
    """Minimal projection — never exposes the password hash."""

    id: str
    email: str
    role: UserRole
    tenant_id: str | None
    created_at: str

    @classmethod
    def from_user(cls, u: User) -> UserOut:
        return cls(
            id=u.id,
            email=u.email,
            role=u.role,
            tenant_id=u.tenant_id,
            created_at=u.created_at.isoformat(),
        )


def _set_session_cookie(response: Response, token: str, expires_iso: str) -> None:
    """Issue an HTTP-only session cookie. Secure + SameSite both follow env so
    the same code works for same-origin prod deploys (Strict) and split-origin
    setups like local dashboard ↔ remote API (None)."""
    # Cast for FastAPI's literal-typed kwarg — we validated the value above.
    samesite_val: Any = _auth_cookie_samesite()
    response.set_cookie(
        key=_AUTH_COOKIE,
        value=token,
        httponly=True,
        secure=_auth_cookie_secure(),
        samesite=samesite_val,
        expires=expires_iso,
        path="/",
    )


def _clear_session_cookie(response: Response) -> None:
    response.delete_cookie(_AUTH_COOKIE, path="/")


@app.post("/auth/login", response_model=UserOut)
async def auth_login(req: LoginRequest, response: Response) -> UserOut:
    try:
        user, session = _auth_service.login(email=req.email, password=req.password)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    _set_session_cookie(response, session.token, session.expires_at.isoformat())
    return UserOut.from_user(user)


@app.post("/auth/logout", status_code=204)
async def auth_logout(request: Request, response: Response) -> Response:
    token = request.cookies.get(_AUTH_COOKIE)
    if token:
        _auth_service.logout(token)
    _clear_session_cookie(response)
    return Response(status_code=204)


@app.get("/auth/me", response_model=UserOut)
async def auth_me(request: Request) -> UserOut:
    token = request.cookies.get(_AUTH_COOKIE)
    try:
        user = _auth_service.authenticate(token)
    except AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return UserOut.from_user(user)


@app.post("/auth/register", response_model=UserOut, status_code=201)
async def auth_register(req: RegisterRequest, request: Request) -> UserOut:
    """Create a new user. When auth enforcement is OFF this endpoint is open
    so the bootstrap-admin script can mint the first admin. When ON, only an
    existing ADMIN can mint more users — that's the production posture."""
    _assert_admin(request)
    try:
        user = _auth_service.register(
            email=req.email,
            password=req.password,
            role=req.role,
            tenant_id=req.tenant_id,
        )
    except AuthError as exc:
        # 409 for duplicate, 422 for validation errors.
        status = 409 if "already exists" in str(exc) else 422
        raise HTTPException(status_code=status, detail=str(exc)) from exc
    return UserOut.from_user(user)


@app.get("/tenants/{tenant_id}/catalog/facts", response_model=list[CatalogFactOut])
async def list_catalog_facts(tenant_id: str, request: Request) -> list[CatalogFactOut]:
    """List every fact in the tenant's Hindsight RAG store. Useful for
    confirming a bulk upload landed and for debugging "the agent isn't citing
    catalog X" issues."""
    _assert_tenant_access(request, tenant_id)
    try:
        _client.tenants.get(tenant_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc
    facts = _client.hindsight.all_for(tenant_id)
    return [
        CatalogFactOut(
            id=f.id,
            source=f.source,
            content=f.content,
            metadata=f.metadata,
            created_at=f.created_at.isoformat(),
        )
        for f in facts
    ]


# --- Skills ----------------------------------------------------------------


@app.get("/skills")
async def list_skills() -> dict[str, list[str]]:
    return {"skills": _client.list_skills()}


@app.post("/skills/invoke")
async def invoke_skill(req: SkillRequest) -> dict[str, Any]:
    return await _client.invoke_skill(req.skill, req.context, req.params)


@app.post("/goal")
async def evaluate_goal(req: GoalRequest) -> dict[str, Any]:
    goal = Goal(
        tenant_id=req.tenant_id,
        goal_type=GoalType(req.goal_type),
        params=req.params | {"message": req.message},
    )
    skill_result = await _client.skills.invoke("lead-qualifier", {}, {"message": req.message})
    context = skill_result.data if skill_result.success else {"intent_score": 0, "tag": "cold"}
    judge_result = _client._judge.judge(goal, context)
    return {
        "goal_id": goal.goal_id,
        "goal_type": goal.goal_type.value,
        "achieved": judge_result.achieved,
        "score": judge_result.score,
        "diagnostics": judge_result.diagnostics,
    }


@app.get("/webhook")
async def webhook_verify(request: Request) -> Response:
    """Meta subscription handshake."""
    params = request.query_params
    challenge = verify_subscription(
        os.environ.get("META_VERIFY_TOKEN", ""),
        params.get("hub.mode", ""),
        params.get("hub.verify_token", ""),
        params.get("hub.challenge", ""),
    )
    if challenge is None:
        return Response(status_code=403, content="forbidden")
    return Response(status_code=200, content=challenge)


@app.post("/webhook")
@limiter.limit(_RATE_WEBHOOK)
async def webhook_receive(request: Request) -> Response:
    """Signed inbound WhatsApp delivery — routes to the owning tenant.

    Unknown phone_number_id returns 200 (we never give Meta a non-2xx that would
    trigger retries) but does nothing else; the event is logged for triage.
    """
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(os.environ.get("META_APP_SECRET", ""), body, signature):
        return Response(status_code=401, content="invalid signature")
    payload = await request.json()

    phone_number_id = extract_phone_number_id(payload)
    tenant = _client.router.try_resolve(phone_number_id) if phone_number_id else None
    if tenant is None:
        return Response(status_code=200, content="no tenant for this phone_number_id")

    messages = parse_messages(tenant_id=tenant.id, body=payload)
    for msg in messages:
        await _process_inbound_message(tenant, msg)
    return Response(status_code=200, content=f"received {len(messages)} for {tenant.slug}")


_webhook_log = logging.getLogger("waseller.webhook")
_FALLBACK_REPLY = "Tuvimos un inconveniente procesando tu mensaje. Te respondemos en unos minutos."


async def _process_inbound_message(tenant: Tenant, msg: InboundMessage) -> None:
    """Process one inbound message: remember it, run the agent, send the reply.

    Every external dependency is wrapped so a single failure (LLM 429,
    gateway 131030 recipient-list block, postgres flap) never:

    1. propagates a 5xx to Meta — Meta retries non-2xx, which floods us
       with duplicates of the same buyer message;
    2. leaves the agent reply un-persisted — we want the conversation
       auditable even when delivery failed, and the next turn's recall
       depends on it.

    The buyer message is always persisted first since it's a local op and
    losing it costs the agent its context for this very turn.
    """
    bid = buyer_id_for(tenant.slug, msg.from_number)

    # 1. Persist the inbound message — best effort, log on failure.
    try:
        await _client.memory.remember(
            bid,
            BuyerInteraction(
                text=msg.text,
                role="buyer",
                metadata={"tenant_id": tenant.id, "message_id": msg.message_id},
            ),
        )
    except Exception as exc:
        _webhook_log.warning("buyer remember failed for %s: %s", bid, str(exc)[:200])

    # 1b. Bot pause check — if a human grabbed this thread (or a previous
    # handoff auto-paused it), the bot stays silent until the pause expires
    # or a human resumes via the dashboard. The buyer message is already
    # persisted so the human sees it in the inbox.
    try:
        if _client.bot_pauses.is_paused(tenant.id, bid):
            return
    except Exception as exc:
        # If the pause registry is unreachable, prefer false-negative (let
        # the bot respond) over false-positive (silence forever) — the
        # buyer always hearing back from somebody is the higher priority.
        _webhook_log.warning("bot pause check failed for %s: %s", bid, str(exc)[:200])

    # 2. Compose the reply. Any LLM / RAG error becomes a canned reply so the
    # buyer always hears back. agent_meta carries the diagnostic.
    try:
        turn = await _client.agent.respond(tenant, bid, msg.text)
        reply = turn.reply
        agent_meta = {
            "model": turn.model,
            "facts_cited": str(len(turn.facts_cited)),
            "history_used": str(turn.history_used),
        }
        # Handoff: if the per-tenant detector tripped, fire the notifier so a
        # human can pick the thread up. Errors are swallowed (logged) — the
        # buyer already got the "te paso con un humano" reply and we don't
        # want a slow webhook to slow down delivery. Metadata flags the turn
        # so the dashboard can render it visibly in the conversation thread.
        if turn.handoff is not None and turn.handoff.escalate:
            agent_meta["handoff"] = "true"
            if turn.handoff.matched_keyword:
                agent_meta["handoff_keyword"] = turn.handoff.matched_keyword
            try:
                await _client.handoff_notifier.notify(
                    tenant=tenant,
                    buyer_id=bid,
                    message=msg.text,
                    decision=turn.handoff,
                )
            except Exception as exc:
                _webhook_log.warning("handoff notify failed for %s: %s", bid, str(exc)[:200])
            # Auto-pause the bot so it stops piping in over the human takeover.
            # auto_pause_hours=0 means "warm handoff" — bot keeps replying — so
            # only pause when the tenant configured a positive window.
            hcfg = tenant.handoff_config
            if hcfg is not None and hcfg.auto_pause_hours > 0:
                try:
                    until = datetime.now(UTC) + timedelta(hours=hcfg.auto_pause_hours)
                    _client.bot_pauses.pause(tenant.id, bid, until)
                    agent_meta["bot_paused_until"] = until.isoformat()
                except Exception as exc:
                    _webhook_log.warning("auto-pause failed for %s: %s", bid, str(exc)[:200])
    except Exception as exc:
        reply = _FALLBACK_REPLY
        agent_meta = {"error": str(exc)[:200]}

    # 3. Try to deliver. Gateway failures (allowed-recipients drop, expired
    # token, WhatsApp 24h window closed, network blip) are isolated here so the
    # reply still gets persisted below. We capture the error in agent_meta for
    # later auditing — the agent row in buyer_interactions then carries the
    # delivery_error field instead of a vendor_message_id.
    vendor_message_id = ""
    try:
        sent = await _client.gateway.send_text(
            to_number=msg.from_number, text=reply, tenant_id=tenant.id
        )
        vendor_message_id = sent.vendor_message_id or ""
    except Exception as exc:
        agent_meta["delivery_error"] = str(exc)[:200]
        _webhook_log.warning("gateway send_text failed for %s: %s", bid, str(exc)[:200])

    # 4. Always persist the agent reply, even on delivery failure — best
    # effort, log on failure so we don't double-fail silently.
    try:
        await _client.memory.remember(
            bid,
            BuyerInteraction(
                text=reply,
                role="agent",
                metadata={"vendor_message_id": vendor_message_id, **agent_meta},
            ),
        )
    except Exception as exc:
        _webhook_log.warning("agent remember failed for %s: %s", bid, str(exc)[:200])
