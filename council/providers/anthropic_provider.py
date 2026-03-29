"""
Anthropic Claude provider adapter for TheCouncil.

Wraps the Anthropic SDK in an OpenAI-compatible interface so that
`council.py`'s debate engine can use Claude models when
ANTHROPIC_API_KEY is set and a claude-* model is requested.

Supported models:
  claude-sonnet-4-20250514   (default / primary per problem spec)
  claude-opus-4-5            (large / higher capability)
  claude-haiku-4-5           (fast / cheap)

Usage (automatic via get_client_for_model):
  The council engine calls get_client_for_model(model) which returns an
  (AsyncOpenAI | AnthropicAdapter, resolved_model) pair. The adapter
  implements the same `.chat.completions.create()` async interface so
  all call sites remain unchanged.
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from typing import Any, AsyncIterator

log = logging.getLogger(__name__)

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
DEFAULT_CLAUDE_MODEL = "claude-sonnet-4-20250514"

CLAUDE_MODELS: dict[str, str] = {
    "anthropic/claude-sonnet-4-20250514": "claude-sonnet-4-20250514",
    "claude-sonnet-4-20250514": "claude-sonnet-4-20250514",
    "anthropic/claude-opus-4-5": "claude-opus-4-5",
    "claude-opus-4-5": "claude-opus-4-5",
    "anthropic/claude-haiku-4-5": "claude-haiku-4-5",
    "claude-haiku-4-5": "claude-haiku-4-5",
    # Legacy aliases
    "anthropic/claude-sonnet-4.6": "claude-sonnet-4-20250514",
    "anthropic/claude-3-5-sonnet-20241022": "claude-3-5-sonnet-20241022",
}


# ---------------------------------------------------------------------------
# Lightweight OpenAI-compatible response shims
# ---------------------------------------------------------------------------


@dataclass
class _Choice:
    index: int
    message: "_Message"
    finish_reason: str = "stop"


@dataclass
class _Message:
    role: str
    content: str


@dataclass
class _Delta:
    content: str = ""
    role: str = "assistant"


@dataclass
class _StreamChoice:
    index: int
    delta: _Delta
    finish_reason: str | None = None


@dataclass
class _ChatCompletion:
    id: str
    choices: list[_Choice]
    model: str
    usage: dict[str, int] = field(default_factory=dict)


@dataclass
class _ChatCompletionChunk:
    id: str
    choices: list[_StreamChoice]
    model: str


class _StreamIterator:
    """Wraps an Anthropic streaming response in an async-iterable of chunks."""

    def __init__(self, stream: Any) -> None:
        self._stream = stream
        self._id = "anth-stream"

    def __aiter__(self) -> AsyncIterator["_ChatCompletionChunk"]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator["_ChatCompletionChunk"]:
        import anthropic  # type: ignore[import]

        async with self._stream as stream:
            async for event in stream:
                if isinstance(event, anthropic.types.RawContentBlockDeltaEvent):
                    delta_text = getattr(event.delta, "text", "")
                    yield _ChatCompletionChunk(
                        id=self._id,
                        model="",
                        choices=[_StreamChoice(index=0, delta=_Delta(content=delta_text))],
                    )
                elif isinstance(event, anthropic.types.MessageStopEvent):
                    yield _ChatCompletionChunk(
                        id=self._id,
                        model="",
                        choices=[
                            _StreamChoice(index=0, delta=_Delta(), finish_reason="stop")
                        ],
                    )


class _Completions:
    """Mimic openai.resources.AsyncCompletions.create()."""

    def __init__(self, client: "AnthropicAdapter") -> None:
        self._client = client

    async def create(
        self,
        *,
        model: str,
        messages: list[dict[str, str]],
        max_tokens: int = 2048,
        temperature: float = 0.7,
        stream: bool = False,
        **kwargs: Any,
    ) -> "_ChatCompletion | _StreamIterator":
        import anthropic  # type: ignore[import]

        client = self._client._get_client()

        # Split system prompt from conversation messages
        system_parts: list[str] = []
        conversation: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_parts.append(msg["content"])
            else:
                conversation.append({"role": msg["role"], "content": msg["content"]})

        system_kwarg: Any = "\n\n".join(system_parts) if system_parts else anthropic.NOT_GIVEN

        if stream:
            raw_stream = client.messages.stream(
                model=model,
                system=system_kwarg,
                messages=conversation,  # type: ignore[arg-type]
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return _StreamIterator(raw_stream)

        response = await client.messages.create(
            model=model,
            system=system_kwarg,
            messages=conversation,  # type: ignore[arg-type]
            max_tokens=max_tokens,
            temperature=temperature,
        )
        content = response.content[0].text if response.content else ""
        return _ChatCompletion(
            id=response.id,
            model=response.model,
            choices=[_Choice(index=0, message=_Message(role="assistant", content=content))],
            usage={
                "prompt_tokens": response.usage.input_tokens,
                "completion_tokens": response.usage.output_tokens,
            },
        )


class _Chat:
    def __init__(self, client: "AnthropicAdapter") -> None:
        self.completions = _Completions(client)


class AnthropicAdapter:
    """Drop-in async adapter matching the `AsyncOpenAI` interface subset used by council.py."""

    def __init__(self, api_key: str) -> None:
        self._api_key = api_key
        self._inner_client: Any = None

    def _get_client(self) -> Any:
        if self._inner_client is None:
            import anthropic  # type: ignore[import]

            self._inner_client = anthropic.AsyncAnthropic(api_key=self._api_key)
        return self._inner_client

    @property
    def chat(self) -> _Chat:
        return _Chat(self)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

_anthropic_adapter: AnthropicAdapter | None = None


def get_anthropic_adapter() -> AnthropicAdapter | None:
    """Return a shared AnthropicAdapter when ANTHROPIC_API_KEY is configured."""
    global _anthropic_adapter
    if not ANTHROPIC_API_KEY:
        return None
    if _anthropic_adapter is None:
        _anthropic_adapter = AnthropicAdapter(api_key=ANTHROPIC_API_KEY)
    return _anthropic_adapter


def is_claude_model(model: str) -> bool:
    """Return True if the model identifier maps to a Claude model."""
    normalized = (model or "").split(":")[0].strip()
    return normalized in CLAUDE_MODELS


def resolve_claude_model(model: str) -> str:
    """Map an OpenRouter-style Claude model ID to the native Anthropic model ID."""
    normalized = model.split(":")[0].strip()
    return CLAUDE_MODELS.get(normalized, normalized)
