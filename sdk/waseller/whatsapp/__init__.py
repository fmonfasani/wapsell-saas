"""WhatsApp layer: webhook (inbound), gateway port + adapters (outbound)."""

from __future__ import annotations

from waseller.whatsapp.gateway import (
    GatewayError,
    InMemoryGateway,
    KapsoGateway,
    OutboundMessage,
    WhatsAppGatewayPort,
)
from waseller.whatsapp.webhook import (
    extract_phone_number_id,
    parse_messages,
    verify_signature,
    verify_subscription,
)

__all__ = [
    "GatewayError",
    "InMemoryGateway",
    "KapsoGateway",
    "OutboundMessage",
    "WhatsAppGatewayPort",
    "extract_phone_number_id",
    "parse_messages",
    "verify_signature",
    "verify_subscription",
]
