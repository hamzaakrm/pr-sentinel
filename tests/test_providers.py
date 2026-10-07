"""Provider wire formats, tested against httpx.MockTransport (no network)."""

import json

import httpx
import pytest

from pr_sentinel.providers import ProviderError
from pr_sentinel.providers.remote import AnthropicProvider, OllamaProvider, OpenAIProvider


def client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_anthropic_request_and_response():
    seen = {}

    def handler(req: httpx.Request):
        seen["url"] = str(req.url)
        seen["headers"] = req.headers
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"findings": []}'}]})

    p = AnthropicProvider(api_key="k", model="m", client=client(handler))
    assert p.complete("sys", "usr") == '{"findings": []}'
    assert seen["url"] == "https://api.anthropic.com/v1/messages"
    assert seen["headers"]["x-api-key"] == "k"
    assert seen["body"]["system"] == "sys"
    assert seen["body"]["messages"] == [{"role": "user", "content": "usr"}]


def test_openai_uses_json_mode_and_custom_base_url():
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    p = OpenAIProvider(api_key="k", base_url="http://local/v1", client=client(handler))
    assert p.complete("s", "u") == "{}"
    assert seen["url"] == "http://local/v1/chat/completions"
    assert seen["body"]["response_format"] == {"type": "json_object"}


def test_ollama():
    def handler(req):
        body = json.loads(req.content)
        assert body["format"] == "json" and body["stream"] is False
        return httpx.Response(200, json={"message": {"content": "{}"}})

    assert OllamaProvider(client=client(handler)).complete("s", "u") == "{}"


def test_retries_on_rate_limit(monkeypatch):
    monkeypatch.setattr("time.sleep", lambda s: None)
    calls = {"n": 0}

    def handler(req):
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(429, headers={"retry-after": "1"})
        return httpx.Response(200, json={"content": [{"type": "text", "text": "ok"}]})

    assert AnthropicProvider(api_key="k", client=client(handler)).complete("s", "u") == "ok"
    assert calls["n"] == 3


def test_client_error_raises():
    p = OpenAIProvider(api_key="k", client=client(lambda r: httpx.Response(401, text="bad key")))
    with pytest.raises(ProviderError, match="401"):
        p.complete("s", "u")


def test_missing_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        AnthropicProvider()


def test_gemini_uses_openai_compatible_endpoint(monkeypatch):
    from pr_sentinel.providers import get_provider

    monkeypatch.setenv("GEMINI_API_KEY", "g-key")
    seen = {}

    def handler(req):
        seen["url"] = str(req.url)
        seen["auth"] = req.headers["authorization"]
        seen["body"] = json.loads(req.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "{}"}}]})

    p = get_provider("gemini", client=client(handler))
    assert p.complete("s", "u") == "{}"
    assert seen["url"] == "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions"
    assert seen["auth"] == "Bearer g-key"
    assert seen["body"]["model"] == "gemini-flash-latest"
