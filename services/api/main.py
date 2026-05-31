"""Waseller internal API (FastAPI).

Fase 0/3/7/10: health, WhatsApp webhook, skills, goals, tenants CRUD (admin).
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from waseller.client import WasellerClient, buyer_id_for
from waseller.goal import Goal, GoalType
from waseller.memory.buyer import BuyerInteraction
from waseller.models import Tenant
from waseller.onboarding import MetaSignupPayload, OnboardingError
from waseller.security.log_filter import install_redaction
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


app = FastAPI(title="Waseller API", version="0.11.0")
_client = WasellerClient(gateway=_build_gateway())

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

# CORS for the admin dashboard (Next.js dev server defaults to :3000; prod
# origins come from WASELLER_DASHBOARD_ORIGINS as a comma-separated list).
_default_origins = "http://localhost:3000,http://127.0.0.1:3000"
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


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "waseller-api"}


# --- Tenants (admin) -------------------------------------------------------


@app.get("/tenants", response_model=list[TenantOut])
async def list_tenants() -> list[TenantOut]:
    return [TenantOut.from_tenant(t) for t in _client.tenants.list()]


@app.post("/tenants", response_model=TenantOut, status_code=201)
async def create_tenant(req: TenantCreate) -> TenantOut:
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
async def get_tenant(tenant_id: str) -> TenantOut:
    try:
        return TenantOut.from_tenant(_client.tenants.get(tenant_id))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc


@app.patch("/tenants/{tenant_id}", response_model=TenantOut)
async def update_tenant(tenant_id: str, req: TenantUpdate) -> TenantOut:
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


@app.get("/tenants/{tenant_id}/soul")
async def get_tenant_soul(tenant_id: str) -> dict[str, str]:
    try:
        return {"soul": _client.soul_for(tenant_id)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="tenant not found") from exc


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
        bid = buyer_id_for(tenant.slug, msg.from_number)
        # 1. Remember the inbound message so the agent has context next turn.
        await _client.memory.remember(
            bid,
            BuyerInteraction(
                text=msg.text,
                role="buyer",
                metadata={"tenant_id": tenant.id, "message_id": msg.message_id},
            ),
        )
        # 2. Full agent loop: recall → RAG → SOUL → LLM → reply. The LLM port
        #    is EchoLLM in dev (deterministic, no network); production swaps
        #    in OpenRouterLLM via the composition root.
        try:
            turn = await _client.agent.respond(tenant, bid, msg.text)
            reply = turn.reply
            agent_meta = {
                "model": turn.model,
                "facts_cited": str(len(turn.facts_cited)),
                "history_used": str(turn.history_used),
            }
        except Exception as exc:  # never let one LLM/RAG error 5xx Meta
            reply = (
                "Tuvimos un inconveniente procesando tu mensaje. Te respondemos en unos minutos."
            )
            agent_meta = {"error": str(exc)[:200]}
        sent = await _client.gateway.send_text(
            to_number=msg.from_number, text=reply, tenant_id=tenant.id
        )
        # 3. Remember the agent's reply too, so the conversation is auditable.
        await _client.memory.remember(
            bid,
            BuyerInteraction(
                text=reply,
                role="agent",
                metadata={"vendor_message_id": sent.vendor_message_id or "", **agent_meta},
            ),
        )
    return Response(status_code=200, content=f"received {len(messages)} for {tenant.slug}")
