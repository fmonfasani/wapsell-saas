"""WhatsApp webhook handling: signature verification + payload parsing.

Meta signs webhook bodies with HMAC-SHA256 (`X-Hub-Signature-256: sha256=<hex>`).
Verification is a pure function so it is exhaustively testable without a live
Meta connection. Parsing normalizes Meta's nested payload into InboundMessage.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from hermesell.models import InboundMessage


def verify_signature(app_secret: str, payload: bytes, signature_header: str) -> bool:
    """Constant-time verify a Meta `X-Hub-Signature-256` header against the body."""
    prefix = "sha256="
    if not signature_header.startswith(prefix):
        return False
    provided = signature_header[len(prefix) :]
    expected = hmac.new(app_secret.encode("utf-8"), payload, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, provided)


def verify_subscription(verify_token: str, mode: str, token: str, challenge: str) -> str | None:
    """Meta GET subscription handshake: return the challenge if the token matches."""
    if mode == "subscribe" and hmac.compare_digest(verify_token, token):
        return challenge
    return None


def extract_phone_number_id(body: dict[str, Any]) -> str | None:
    """Pull the WhatsApp ``phone_number_id`` out of a Meta webhook payload.

    Meta nests it at ``entry[*].changes[*].value.metadata.phone_number_id``.
    Returns the first one found, or None if the payload doesn't carry one.
    """
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            metadata = change.get("value", {}).get("metadata", {})
            pnid = metadata.get("phone_number_id")
            if isinstance(pnid, str) and pnid:
                return pnid
    return None


def parse_messages(tenant_id: str, body: dict[str, Any]) -> list[InboundMessage]:
    """Extract normalized inbound text messages from a Meta webhook payload.

    Tolerant of the deep, optional structure Meta sends; non-text events yield
    nothing rather than raising.
    """
    messages: list[InboundMessage] = []
    for entry in body.get("entry", []):
        for change in entry.get("changes", []):
            value = change.get("value", {})
            for msg in value.get("messages", []):
                if msg.get("type") != "text":
                    continue
                messages.append(
                    InboundMessage(
                        tenant_id=tenant_id,
                        from_number=str(msg.get("from", "")),
                        text=str(msg.get("text", {}).get("body", "")),
                        message_id=str(msg.get("id", "")),
                    )
                )
    return messages
