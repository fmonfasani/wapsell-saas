"""HermesSell internal API (FastAPI).

Fase 0/3: exposes health + the WhatsApp webhook (subscription handshake +
signed inbound delivery). Business handling is wired in later phases; for now
inbound messages are parsed and acknowledged.
"""

from __future__ import annotations

import os

from fastapi import FastAPI, Request, Response

from hermesell.whatsapp.webhook import parse_messages, verify_signature, verify_subscription

app = FastAPI(title="HermesSell API", version="0.1.0")


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "service": "hermesell-api"}


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
    """Signed inbound WhatsApp delivery."""
    body = await request.body()
    signature = request.headers.get("X-Hub-Signature-256", "")
    if not verify_signature(os.environ.get("META_APP_SECRET", ""), body, signature):
        return Response(status_code=401, content="invalid signature")
    # tenant resolution by phone_number_id lands in Fase 8; placeholder for now.
    messages = parse_messages(tenant_id="default", body=await request.json())
    return Response(status_code=200, content=f"received {len(messages)}")
