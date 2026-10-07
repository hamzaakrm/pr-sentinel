"""HTTP-based providers. Implemented with plain httpx so there are no vendor SDK deps."""

from __future__ import annotations

import os

from .base import LLMProvider, ProviderError


def _require_env(var: str, provider: str) -> str:
    val = os.environ.get(var)
    if not val:
        raise ProviderError(f"{provider}: environment variable {var} is not set")
    return val


class AnthropicProvider(LLMProvider):
    name = "anthropic"
    default_model = "claude-sonnet-4-5"

    def __init__(self, *a, api_key: str | None = None, base_url: str | None = None, **kw):
        super().__init__(*a, **kw)
        self.api_key = api_key or _require_env("ANTHROPIC_API_KEY", self.name)
        self.base_url = (base_url or os.environ.get("ANTHROPIC_BASE_URL")
                         or "https://api.anthropic.com").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        data = self._post(
            f"{self.base_url}/v1/messages",
            headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"},
            json={"model": self.model, "max_tokens": 4096, "temperature": self.temperature,
                  "system": system, "messages": [{"role": "user", "content": user}]},
        )
        return "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")


class OpenAIProvider(LLMProvider):
    """OpenAI or any OpenAI-compatible endpoint (Azure, Groq, Together, LM Studio...)."""

    name = "openai"
    default_model = "gpt-4.1-mini"

    def __init__(self, *a, api_key: str | None = None, base_url: str | None = None, **kw):
        super().__init__(*a, **kw)
        self.api_key = api_key or _require_env("OPENAI_API_KEY", self.name)
        self.base_url = (base_url or os.environ.get("OPENAI_BASE_URL")
                         or "https://api.openai.com/v1").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        data = self._post(
            f"{self.base_url}/chat/completions",
            headers={"Authorization": f"Bearer {self.api_key}"},
            json={"model": self.model, "temperature": self.temperature,
                  "response_format": {"type": "json_object"},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
        )
        try:
            return data["choices"][0]["message"]["content"] or ""
        except (KeyError, IndexError) as e:
            raise ProviderError(f"openai: unexpected response shape: {data}") from e


class OllamaProvider(LLMProvider):
    """Local models via Ollama — free and fully offline."""

    name = "ollama"
    default_model = "qwen2.5-coder:7b"

    def __init__(self, *a, base_url: str | None = None, **kw):
        kw.setdefault("timeout", 600.0)
        super().__init__(*a, **kw)
        self.base_url = (base_url or os.environ.get("OLLAMA_HOST")
                         or "http://localhost:11434").rstrip("/")

    def complete(self, system: str, user: str) -> str:
        data = self._post(
            f"{self.base_url}/api/chat",
            headers={},
            json={"model": self.model, "stream": False, "format": "json",
                  "options": {"temperature": self.temperature, "num_ctx": 16384},
                  "messages": [{"role": "system", "content": system},
                               {"role": "user", "content": user}]},
        )
        return (data.get("message") or {}).get("content", "")


class GeminiProvider(OpenAIProvider):
    """Google Gemini via its OpenAI-compatible endpoint (has a free tier)."""

    name = "gemini"
    default_model = "gemini-flash-latest"

    def __init__(self, *a, api_key: str | None = None, base_url: str | None = None, **kw):
        super().__init__(
            *a,
            api_key=api_key or _require_env("GEMINI_API_KEY", "gemini"),
            base_url=base_url or os.environ.get("GEMINI_BASE_URL")
            or "https://generativelanguage.googleapis.com/v1beta/openai",
            **kw,
        )
