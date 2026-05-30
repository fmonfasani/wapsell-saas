"""HermesSell internal API (FastAPI).

Fase 0/3/7: health, WhatsApp webhook, skills, goals.
"""

from __future__ import annotations

import os
from typing import Any

from fastapi import FastAPI, Request, Response
from pydantic import BaseModel, Field

from hermesell.client import HermesSellClient, buyer_id_for
from hermesell.goal import Goal, GoalType
from hermesell.memory.buyer import BuyerInteraction
from hermesell.whatsapp.webhook import (
    extract_phone_number_id,
    parse_messages,
    verify_signature,
    verify_subscription,
)

app = FastAPI(title="HermesSell API", version="0.2.0")
_client = HermesSellClient()


class GoalRequest(BaseModel):
    tenant_id: str = "default"
    goal_type: str = "qualify"
    message: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


class SkillRequest(BaseModel):
    skill: str
    context: dict[str, Any] = Field(default_factory=dict)
    params: dict[str, Any] = Field(default_factory=dict)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hermesell-api"}


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
        await _client.memory.remember(
            buyer_id_for(tenant.slug, msg.from_number),
            BuyerInteraction(
                text=msg.text,
                role="buyer",
                metadata={"tenant_id": tenant.id, "message_id": msg.message_id},
            ),
        )
    return Response(status_code=200, content=f"received {len(messages)} for {tenant.slug}")
