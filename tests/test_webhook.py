"""Tests for WhatsApp webhook signature verification + payload parsing."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from wapsell.whatsapp import parse_messages, verify_signature, verify_subscription

pytestmark = pytest.mark.unit

_SECRET = "app-secret"


def _sign(secret: str, payload: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def test_valid_signature_accepted() -> None:
    payload = b'{"hello":"world"}'
    assert verify_signature(_SECRET, payload, _sign(_SECRET, payload))


def test_tampered_body_rejected() -> None:
    payload = b'{"hello":"world"}'
    sig = _sign(_SECRET, payload)
    assert not verify_signature(_SECRET, b'{"hello":"evil"}', sig)


def test_wrong_secret_rejected() -> None:
    payload = b"data"
    assert not verify_signature("other", payload, _sign(_SECRET, payload))


def test_malformed_header_rejected() -> None:
    assert not verify_signature(_SECRET, b"x", "not-a-signature")


def test_subscription_handshake() -> None:
    assert verify_subscription("tok", "subscribe", "tok", "challenge-123") == "challenge-123"
    assert verify_subscription("tok", "subscribe", "wrong", "c") is None
    assert verify_subscription("tok", "unsubscribe", "tok", "c") is None


def test_parse_extracts_text_messages_only() -> None:
    body = {
        "entry": [
            {
                "changes": [
                    {
                        "value": {
                            "messages": [
                                {
                                    "type": "text",
                                    "from": "549111",
                                    "id": "m1",
                                    "text": {"body": "hola, precio?"},
                                },
                                {"type": "image", "from": "549111", "id": "m2"},
                            ]
                        }
                    }
                ]
            }
        ]
    }
    msgs = parse_messages("tenant-1", body)
    assert len(msgs) == 1
    assert msgs[0].text == "hola, precio?"
    assert msgs[0].from_number == "549111"


def test_parse_tolerates_empty_payload() -> None:
    assert parse_messages("t", json.loads("{}")) == []
