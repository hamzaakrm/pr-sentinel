"""Provider interface: every LLM backend just turns (system, user) prompts into text."""

from __future__ import annotations

import time
from abc import ABC, abstractmethod

import httpx


class ProviderError(RuntimeError):
    pass


class LLMProvider(ABC):
    name: str = "base"
    default_model: str = ""

    def __init__(self, model: str | None = None, temperature: float = 0.1,
                 timeout: float = 120.0, client: httpx.Client | None = None):
        self.model = model or self.default_model
        self.temperature = temperature
        self.client = client or httpx.Client(timeout=timeout)

    @abstractmethod
    def complete(self, system: str, user: str) -> str:
        """Return the raw text of the model's reply."""

    def _post(self, url: str, *, headers: dict, json: dict, retries: int = 4) -> dict:
        """POST with exponential backoff on rate limits and transient server errors."""
        delay = 2.0
        for attempt in range(retries + 1):
            try:
                resp = self.client.post(url, headers=headers, json=json)
            except httpx.TransportError as e:
                if attempt == retries:
                    raise ProviderError(f"{self.name}: network error: {e}") from e
                time.sleep(delay)
                delay *= 2
                continue
            if resp.status_code in (429, 500, 502, 503, 504, 529) and attempt < retries:
                retry_after = resp.headers.get("retry-after")
                time.sleep(min(float(retry_after), 60) if retry_after and retry_after.isdigit() else delay)
                delay *= 2
                continue
            if resp.status_code >= 400:
                raise ProviderError(f"{self.name}: HTTP {resp.status_code}: {resp.text[:500]}")
            return resp.json()
        raise ProviderError(f"{self.name}: exhausted retries")

    def __repr__(self) -> str:
        return f"{self.name}:{self.model}"
