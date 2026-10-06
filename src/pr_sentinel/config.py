"""Configuration loaded from `.pr-sentinel.yml` plus environment variable overrides."""

from __future__ import annotations

import fnmatch
import os
from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from .models import Severity

DEFAULT_IGNORE = [
    "*.lock", "package-lock.json", "yarn.lock", "poetry.lock", "*.min.js", "*.min.css",
    "*.svg", "*.png", "*.jpg", "*.gif", "*.pdf", "dist/*", "build/*", "vendor/*",
    "node_modules/*", "*.snap",
]


class Config(BaseModel):
    provider: str = "anthropic"  # anthropic | openai | ollama | fake
    model: str | None = None
    temperature: float = 0.1
    max_files: int = 25
    max_chunk_chars: int = 24_000  # diff text per LLM call
    min_severity: Severity = Severity.LOW
    max_comments: int = 30
    static_analysis: bool = True
    ignore: list[str] = Field(default_factory=lambda: list(DEFAULT_IGNORE))
    focus: list[str] = Field(
        default_factory=lambda: ["bugs", "security", "performance", "maintainability"]
    )
    extra_instructions: str = ""
    fail_on: Severity | None = None  # exit non-zero if a finding >= this severity exists

    def is_ignored(self, path: str) -> bool:
        return any(
            fnmatch.fnmatch(path, pat) or fnmatch.fnmatch(Path(path).name, pat)
            for pat in self.ignore
        )


ENV_MAP = {
    "PR_SENTINEL_PROVIDER": "provider",
    "PR_SENTINEL_MODEL": "model",
    "PR_SENTINEL_MIN_SEVERITY": "min_severity",
    "PR_SENTINEL_MAX_COMMENTS": "max_comments",
    "PR_SENTINEL_FAIL_ON": "fail_on",
}


def load_config(path: str | os.PathLike | None = None, **overrides) -> Config:
    data: dict = {}
    candidates = [Path(path)] if path else [Path(".pr-sentinel.yml"), Path(".pr-sentinel.yaml")]
    for p in candidates:
        if p.is_file():
            loaded = yaml.safe_load(p.read_text()) or {}
            if not isinstance(loaded, dict):
                raise ValueError(f"{p} must contain a YAML mapping")
            if "ignore" in loaded and loaded.pop("extend_default_ignore", True):
                loaded["ignore"] = DEFAULT_IGNORE + list(loaded["ignore"])
            data.update(loaded)
            break
    for env, key in ENV_MAP.items():
        if os.environ.get(env):
            data[key] = os.environ[env]
    data.update({k: v for k, v in overrides.items() if v is not None})
    return Config(**data)
