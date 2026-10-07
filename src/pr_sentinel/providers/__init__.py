"""Pluggable LLM backends. Add a provider by subclassing LLMProvider and registering it here."""

from __future__ import annotations

from .base import LLMProvider, ProviderError
from .fake import FakeProvider
from .remote import AnthropicProvider, GeminiProvider, OllamaProvider, OpenAIProvider

REGISTRY: dict[str, type[LLMProvider]] = {
    "anthropic": AnthropicProvider,
    "claude": AnthropicProvider,
    "openai": OpenAIProvider,
    "gemini": GeminiProvider,
    "ollama": OllamaProvider,
    "fake": FakeProvider,
}


def get_provider(name: str, **kwargs) -> LLMProvider:
    try:
        cls = REGISTRY[name.lower()]
    except KeyError:
        raise ProviderError(
            f"Unknown provider '{name}'. Choose from: {', '.join(sorted(set(REGISTRY)))}"
        ) from None
    return cls(**kwargs)


__all__ = ["LLMProvider", "ProviderError", "get_provider", "REGISTRY"]
