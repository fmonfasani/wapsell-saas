"""Tests for the LLM port + adapters (Echo, Scripted, OpenRouter)."""

from __future__ import annotations

from typing import Any

import pytest

from waseller.llm import (
    EchoLLM,
    LLMError,
    LLMMessage,
    LLMPort,
    OpenRouterLLM,
    ScriptedLLM,
)

pytestmark = pytest.mark.unit


class TestProtocolConformance:
    def test_echo_satisfies_port(self) -> None:
        assert isinstance(EchoLLM(), LLMPort)

    def test_scripted_satisfies_port(self) -> None:
        assert isinstance(ScriptedLLM(), LLMPort)


class TestEchoLLM:
    async def test_quotes_last_user_message(self) -> None:
        llm = EchoLLM()
        reply = await llm.complete(
            [
                LLMMessage(role="system", content="be nice"),
                LLMMessage(role="user", content="hola"),
            ],
            model="x/y",
        )
        assert "hola" in reply.text
        assert reply.model == "x/y"
        assert reply.metadata["adapter"] == "echo"

    async def test_works_without_user_message(self) -> None:
        llm = EchoLLM()
        reply = await llm.complete([LLMMessage(role="system", content="hi")], model="m")
        assert reply.text


class TestScriptedLLM:
    async def test_returns_queued_replies_in_order(self) -> None:
        llm = ScriptedLLM(replies=["first", "second"])
        a = await llm.complete([LLMMessage(role="user", content="?")], model="m")
        b = await llm.complete([LLMMessage(role="user", content="?")], model="m")
        assert (a.text, b.text) == ("first", "second")

    async def test_records_each_call(self) -> None:
        llm = ScriptedLLM(replies=["x"])
        await llm.complete([LLMMessage(role="user", content="probe")], model="m")
        assert len(llm.calls) == 1
        assert llm.calls[0][0].content == "probe"

    async def test_raises_when_empty(self) -> None:
        llm = ScriptedLLM(replies=[])
        with pytest.raises(LLMError):
            await llm.complete([LLMMessage(role="user", content="?")], model="m")


class _FakeResponse:
    def __init__(self, status_code: int, body: dict[str, Any] | None = None, text: str = ""):
        self.status_code = status_code
        self._body = body or {}
        self.text = text

    def json(self) -> dict[str, Any]:
        return self._body


class _FakeHttp:
    """Captures the request and returns a pre-baked response."""

    def __init__(self, response: _FakeResponse) -> None:
        self.response = response
        self.last_url: str | None = None
        self.last_json: dict[str, Any] | None = None
        self.last_headers: dict[str, str] | None = None

    async def post(
        self,
        url: str,
        *,
        json: dict[str, Any],
        headers: dict[str, str],
        timeout: float,  # noqa: ASYNC109 — mimics httpx.AsyncClient.post signature
    ) -> _FakeResponse:
        self.last_url = url
        self.last_json = json
        self.last_headers = headers
        return self.response


class TestOpenRouterLLM:
    async def test_happy_path_parses_choice(self) -> None:
        http = _FakeHttp(
            _FakeResponse(
                200,
                {
                    "choices": [{"message": {"content": "respuesta"}}],
                    "usage": {"total_tokens": 17},
                },
            )
        )
        llm = OpenRouterLLM(api_key="sk-test", http=http)
        reply = await llm.complete(
            [
                LLMMessage(role="system", content="be helpful"),
                LLMMessage(role="user", content="cuanto sale?"),
            ],
            model="anthropic/claude-3-haiku",
        )
        assert reply.text == "respuesta"
        assert reply.model == "anthropic/claude-3-haiku"
        assert reply.metadata["usage"] == {"total_tokens": 17}
        # Body shape matches OpenAI-compatible /chat/completions
        assert http.last_json is not None
        assert http.last_json["model"] == "anthropic/claude-3-haiku"
        assert http.last_json["messages"][0] == {"role": "system", "content": "be helpful"}
        assert http.last_url and http.last_url.endswith("/chat/completions")
        # Auth + OpenRouter attribution headers present
        assert http.last_headers is not None
        assert http.last_headers["Authorization"] == "Bearer sk-test"
        assert "HTTP-Referer" in http.last_headers
        assert "X-Title" in http.last_headers

    async def test_rejects_empty_api_key(self) -> None:
        with pytest.raises(LLMError):
            OpenRouterLLM(api_key="")

    async def test_raises_on_http_error_status(self) -> None:
        http = _FakeHttp(_FakeResponse(429, {}, text="rate limited"))
        llm = OpenRouterLLM(api_key="sk-test", http=http)
        with pytest.raises(LLMError, match="429"):
            await llm.complete([LLMMessage(role="user", content="?")], model="m")

    async def test_raises_on_unexpected_response_shape(self) -> None:
        # Missing "choices" — must not silently return empty text
        http = _FakeHttp(_FakeResponse(200, {"unexpected": True}))
        llm = OpenRouterLLM(api_key="sk-test", http=http)
        with pytest.raises(LLMError, match="response shape"):
            await llm.complete([LLMMessage(role="user", content="?")], model="m")
