"""LLM boundary — what the agent loop needs from a language model.

The port is intentionally narrow: ``complete(messages, *, model, ...)`` returns
a reply. No streaming, no tool-use, no embeddings — those are different ports.
Three adapters ship today:

- :class:`EchoLLM` — deterministic; replies are derived from inputs. Default in
  dev/tests so nothing calls the network unless explicitly wired.
- :class:`ScriptedLLM` — replies from a pre-loaded queue, surfacing the last
  ``messages`` for assertions. Used in unit tests for the agent loop.
- :class:`OpenRouterLLM` — production adapter (httpx). Routes the tenant's
  configured model name to OpenRouter's OpenAI-compatible ``/chat/completions``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Protocol, runtime_checkable

Role = Literal["system", "user", "assistant"]


@dataclass(frozen=True, slots=True)
class LLMMessage:
    role: Role
    content: str


@dataclass(frozen=True, slots=True)
class LLMReply:
    text: str
    model: str
    # Vendor-specific extras (usage, finish_reason, latency_ms…) live here so
    # the port stays stable while observability grows.
    metadata: dict[str, Any] = field(default_factory=dict)


class LLMError(RuntimeError):
    """LLM call failed (network, auth, rate-limit, parse). Wraps adapter errors."""

    code = "waseller.llm.error"


@runtime_checkable
class LLMPort(Protocol):
    """Single-shot chat completion. Async because real adapters are network-bound."""

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.4,
    ) -> LLMReply: ...


# --- Adapters --------------------------------------------------------------


@dataclass(slots=True)
class EchoLLM:
    """Deterministic adapter — formats the last user message into a templated
    reply. Useful for local dev, smoke tests, and as the safe default."""

    template: str = "Recibimos tu mensaje. Te respondemos en breve con la información del catálogo."

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.4,
    ) -> LLMReply:
        last_user = next((m.content for m in reversed(messages) if m.role == "user"), "")
        echo = f"{self.template} (te dijiste: {last_user[:120]})" if last_user else self.template
        return LLMReply(text=echo, model=model, metadata={"adapter": "echo"})


@dataclass(slots=True)
class ScriptedLLM:
    """Test double — pops replies off a queue and records every call.

    Raises :class:`LLMError` if the queue is empty (so tests fail loudly rather
    than receiving stale stubs by accident).
    """

    replies: list[str] = field(default_factory=list)
    calls: list[list[LLMMessage]] = field(default_factory=list)

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.4,
    ) -> LLMReply:
        self.calls.append(list(messages))
        if not self.replies:
            raise LLMError("ScriptedLLM ran out of canned replies")
        return LLMReply(
            text=self.replies.pop(0),
            model=model,
            metadata={"adapter": "scripted", "call_index": len(self.calls) - 1},
        )


# OpenRouter's chat-completions surface is OpenAI-compatible; the adapter only
# needs an httpx-like ``post`` to be testable. We keep the import string-lazy so
# the SDK doesn't drag httpx into projects that only use EchoLLM.

_HTTP_ERROR_THRESHOLD = 400


class OpenRouterLLM:
    """Production adapter (OpenRouter, OpenAI-compatible /chat/completions).

    ``http`` is duck-typed so tests can inject a fake without httpx — anything
    with ``async post(url, json, headers, timeout) -> response`` works (the
    response must expose ``status_code``, ``json()``, and ``text``).
    """

    BASE_URL = "https://openrouter.ai/api/v1"

    def __init__(
        self,
        api_key: str,
        *,
        http: Any | None = None,  # noqa: ANN401 — duck-typed httpx-like client
        base_url: str | None = None,
        timeout_s: float = 30.0,
        referer: str = "https://github.com/fmonfasani/waseller",
        title: str = "Waseller",
    ) -> None:
        if not api_key:
            raise LLMError("OpenRouterLLM requires a non-empty api_key")
        self._api_key = api_key
        self._http = http  # lazy-init httpx.AsyncClient if None on first use
        self._base_url = (base_url or self.BASE_URL).rstrip("/")
        self._timeout_s = timeout_s
        self._referer = referer
        self._title = title

    async def _client(self) -> Any:  # noqa: ANN401 — see __init__
        if self._http is not None:
            return self._http
        # Lazy import — keeps httpx a soft dep at module level.
        import httpx  # noqa: PLC0415 — see comment above

        self._http = httpx.AsyncClient(timeout=self._timeout_s)
        return self._http

    async def complete(
        self,
        messages: list[LLMMessage],
        *,
        model: str,
        max_tokens: int = 512,
        temperature: float = 0.4,
    ) -> LLMReply:
        body = {
            "model": model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "max_tokens": max_tokens,
            "temperature": temperature,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
            # OpenRouter asks for these so usage shows up in the right project.
            "HTTP-Referer": self._referer,
            "X-Title": self._title,
        }
        client = await self._client()
        try:
            res = await client.post(
                f"{self._base_url}/chat/completions",
                json=body,
                headers=headers,
                timeout=self._timeout_s,
            )
        except LLMError:
            raise
        except Exception as exc:
            raise LLMError(f"openrouter request failed: {exc}") from exc

        if getattr(res, "status_code", 0) >= _HTTP_ERROR_THRESHOLD:
            raise LLMError(f"openrouter {res.status_code}: {getattr(res, 'text', '<no body>')}")
        try:
            data = res.json()
            choice = data["choices"][0]["message"]["content"]
        except (KeyError, IndexError, ValueError) as exc:
            raise LLMError(f"openrouter response shape unexpected: {exc}") from exc

        usage = data.get("usage", {}) if isinstance(data, dict) else {}
        return LLMReply(
            text=str(choice),
            model=model,
            metadata={"adapter": "openrouter", "usage": usage},
        )
