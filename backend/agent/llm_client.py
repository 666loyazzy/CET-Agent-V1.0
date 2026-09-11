"""LLM provider abstraction with streaming.

Supports Anthropic and any OpenAI-compatible endpoint (OpenAI, DeepSeek, ...).
Each client exposes an async `stream(messages, system)` that yields text chunks.
"""

from __future__ import annotations

from typing import AsyncIterator, Protocol

from anthropic import AsyncAnthropic
from openai import AsyncOpenAI

from backend.config import settings


class ChatMessage(dict):
    """Minimal typed dict for {role, content} messages."""


class LLMClient(Protocol):
    async def stream(
        self,
        messages: list[dict],
        system: str,
    ) -> AsyncIterator[str]:
        ...


class AnthropicClient:
    def __init__(self, api_key: str, model: str):
        if not api_key:
            raise ValueError("ANTHROPIC_API_KEY is empty. Set it in .env.")
        self._client = AsyncAnthropic(api_key=api_key)
        self._model = model

    async def stream(
        self,
        messages: list[dict],
        system: str,
    ) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=4096,
            system=system,
            messages=messages,
        ) as stream:
            async for text in stream.text_stream:
                yield text


class OpenAICompatClient:
    def __init__(self, api_key: str, base_url: str, model: str):
        if not api_key:
            raise ValueError("OPENAI_API_KEY is empty. Set it in .env.")
        self._client = AsyncOpenAI(api_key=api_key, base_url=base_url)
        self._model = model

    async def stream(
        self,
        messages: list[dict],
        system: str,
    ) -> AsyncIterator[str]:
        full_messages = [{"role": "system", "content": system}] + messages
        stream = await self._client.chat.completions.create(
            model=self._model,
            messages=full_messages,
            stream=True,
            max_tokens=4096,
        )
        async for chunk in stream:
            delta = chunk.choices[0].delta.content if chunk.choices else None
            if delta:
                yield delta


def get_llm_client() -> LLMClient:
    provider = settings.llm_provider
    if provider == "anthropic":
        return AnthropicClient(
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
        )
    if provider in ("openai", "deepseek"):
        return OpenAICompatClient(
            api_key=settings.openai_api_key,
            base_url=settings.openai_base_url,
            model=settings.openai_model,
        )
    raise ValueError(f"Unknown LLM_PROVIDER: {provider}")
