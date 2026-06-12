"""Tests for security primitives: AES-256-GCM cipher + log redaction filter."""

from __future__ import annotations

import base64
import logging

import pytest

from wapsell.security import (
    CryptoError,
    SecretRedactingFilter,
    TokenCipher,
    generate_key,
    install_redaction,
    redact,
)
from wapsell.security.crypto import key_from_env

pytestmark = pytest.mark.unit


# --- Crypto ---------------------------------------------------------------


class TestGenerateKey:
    def test_decodes_to_32_bytes(self) -> None:
        key = generate_key()
        decoded = base64.urlsafe_b64decode(key + "=" * ((-len(key)) % 4))
        assert len(decoded) == 32

    def test_each_call_is_unique(self) -> None:
        assert generate_key() != generate_key()


class TestKeyFromEnv:
    def test_loads_a_valid_key(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WAPSELL_ENCRYPTION_KEY", generate_key())
        key = key_from_env()
        assert len(key) == 32

    def test_missing_var_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("WAPSELL_ENCRYPTION_KEY", raising=False)
        with pytest.raises(CryptoError, match="missing env var"):
            key_from_env()

    def test_wrong_length_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # Valid base64, but only 16 bytes — would silently downgrade to AES-128.
        monkeypatch.setenv("WAPSELL_ENCRYPTION_KEY", base64.urlsafe_b64encode(b"x" * 16).decode())
        with pytest.raises(CryptoError, match="32 bytes"):
            key_from_env()

    def test_non_base64_raises(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WAPSELL_ENCRYPTION_KEY", "!!!not base64!!!")
        with pytest.raises(CryptoError, match="base64"):
            key_from_env()


class TestTokenCipher:
    @pytest.fixture
    def cipher(self) -> TokenCipher:
        return TokenCipher(base64.urlsafe_b64decode(generate_key() + "="))

    def test_round_trips_plaintext(self, cipher: TokenCipher) -> None:
        plain = "EAAg...long-meta-token..."
        token = cipher.encrypt(plain)
        assert cipher.decrypt(token) == plain

    def test_each_encryption_uses_a_fresh_nonce(self, cipher: TokenCipher) -> None:
        # Two encryptions of the same plaintext MUST produce different ciphertext
        # — otherwise attackers can recognize repeated values.
        assert cipher.encrypt("same") != cipher.encrypt("same")

    def test_decrypt_with_wrong_key_fails(self) -> None:
        a = TokenCipher(base64.urlsafe_b64decode(generate_key() + "="))
        b = TokenCipher(base64.urlsafe_b64decode(generate_key() + "="))
        token = a.encrypt("secret")
        with pytest.raises(CryptoError, match="authentication tag"):
            b.decrypt(token)

    def test_tampered_ciphertext_fails(self, cipher: TokenCipher) -> None:
        token = cipher.encrypt("integrity-matters")
        # Flip a byte in the middle of the ciphertext portion.
        tampered = token[:-4] + ("A" if token[-4] != "A" else "B") + token[-3:]
        with pytest.raises(CryptoError):
            cipher.decrypt(tampered)

    def test_associated_data_is_bound_to_ciphertext(self, cipher: TokenCipher) -> None:
        # AAD lets us bind a token to a tenant_id so it can't be replayed under
        # a different identity even if the DB row is moved across rows.
        token = cipher.encrypt("payload", associated_data=b"tenant-A")
        assert cipher.decrypt(token, associated_data=b"tenant-A") == "payload"
        with pytest.raises(CryptoError):
            cipher.decrypt(token, associated_data=b"tenant-B")

    def test_wrong_key_size_rejected(self) -> None:
        with pytest.raises(CryptoError, match="32 bytes"):
            TokenCipher(b"short")

    def test_malformed_token_rejected(self, cipher: TokenCipher) -> None:
        with pytest.raises(CryptoError):
            cipher.decrypt("!!!not valid base64!!!")
        with pytest.raises(CryptoError, match="shorter"):
            cipher.decrypt(base64.urlsafe_b64encode(b"tiny").decode())

    def test_from_env_constructs_from_key_from_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("WAPSELL_ENCRYPTION_KEY", generate_key())
        cipher = TokenCipher.from_env()
        assert cipher.decrypt(cipher.encrypt("x")) == "x"


# --- Log redaction --------------------------------------------------------


class TestRedact:
    @pytest.mark.parametrize(
        ("raw", "must_not_contain", "must_still_contain"),
        [
            (
                "OPENROUTER_API_KEY=sk-or-abcd1234efgh5678 user logged in",
                "sk-or-abcd1234efgh5678",
                "OPENROUTER_API_KEY",
            ),
            (
                "META_APP_SECRET='supersecret!' something else",
                "supersecret",
                "META_APP_SECRET",
            ),
            (
                "Authorization: Bearer eyJhbGciOi.payload.signature",
                "eyJhbGciOi.payload.signature",
                "Authorization",
            ),
            (
                "config dict: SOME_TOKEN=tk_live_abc123",
                "tk_live_abc123",
                "SOME_TOKEN",
            ),
            (
                "X-Hub-Signature-256: sha256=deadbeefcafebabe",
                "deadbeefcafebabe",
                "X-Hub-Signature-256",
            ),
            (
                "naked key sk-proj-AAAAAAAAAAAAAAAA snuck in",
                "sk-proj-AAAAAAAAAAAAAAAA",
                "naked key",
            ),
        ],
    )
    def test_masks_value_keeps_key(
        self, raw: str, must_not_contain: str, must_still_contain: str
    ) -> None:
        out = redact(raw)
        assert must_not_contain not in out
        assert must_still_contain in out
        assert "<redacted>" in out

    def test_passes_through_safe_lines(self) -> None:
        msg = "tenant acme-corp processed 3 messages in 12ms"
        assert redact(msg) == msg

    def test_idempotent(self) -> None:
        once = redact("OPENROUTER_API_KEY=sk-test1234567890ab")
        twice = redact(once)
        assert once == twice


class TestSecretRedactingFilter:
    def _captured_records(
        self, logger: logging.Logger
    ) -> tuple[list[logging.LogRecord], logging.Handler]:
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture()
        logger.addHandler(handler)
        logger.setLevel(logging.DEBUG)
        return records, handler

    def test_filter_redacts_before_handler_sees_record(self) -> None:
        logger = logging.getLogger("wapsell.tests.redact-1")
        logger.handlers.clear()
        logger.filters.clear()
        logger.addFilter(SecretRedactingFilter())
        records, handler = self._captured_records(logger)

        logger.info("got OPENROUTER_API_KEY=sk-or-leaky9999 from env")

        logger.removeHandler(handler)
        assert len(records) == 1
        emitted = records[0].getMessage()
        assert "sk-or-leaky9999" not in emitted
        assert "<redacted>" in emitted

    def test_filter_redacts_args_format(self) -> None:
        # Args-style formatting is the easy way to leak secrets:
        # log.info("got %s", api_key) bypasses any per-call sanitization.
        logger = logging.getLogger("wapsell.tests.redact-2")
        logger.handlers.clear()
        logger.filters.clear()
        logger.addFilter(SecretRedactingFilter())
        records, handler = self._captured_records(logger)

        logger.info("config: %s", "META_APP_SECRET=verysecret123")

        logger.removeHandler(handler)
        assert "verysecret123" not in records[0].getMessage()

    def test_install_redaction_returns_filter_for_cleanup(self) -> None:
        logger = logging.getLogger("wapsell.tests.install")
        logger.handlers.clear()
        logger.filters.clear()
        flt = install_redaction(logger)
        assert flt in logger.filters
        logger.removeFilter(flt)
        assert flt not in logger.filters
