"""Core data models shared across the pipeline."""

from __future__ import annotations

from enum import Enum

from pydantic import BaseModel, Field, field_validator


class Severity(str, Enum):
    INFO = "info"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

    @property
    def rank(self) -> int:
        return ["info", "low", "medium", "high", "critical"].index(self.value)

    @property
    def icon(self) -> str:
        return {
            "info": "💬",
            "low": "🔹",
            "medium": "⚠️",
            "high": "🔶",
            "critical": "🛑",
        }[self.value]


class Category(str, Enum):
    BUG = "bug"
    SECURITY = "security"
    PERFORMANCE = "performance"
    STYLE = "style"
    MAINTAINABILITY = "maintainability"
    TESTING = "testing"


class Finding(BaseModel):
    """A single review comment anchored to a line in the new version of a file."""

    file: str
    line: int = Field(ge=1)
    severity: Severity = Severity.MEDIUM
    category: Category = Category.BUG
    title: str
    body: str = ""
    suggestion: str | None = None
    source: str = "llm"  # "llm", "ruff", "bandit", ...
    rule: str | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def _norm_severity(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            aliases = {"warning": "medium", "error": "high", "blocker": "critical", "minor": "low"}
            v = aliases.get(v, v)
            if v not in {s.value for s in Severity}:
                return Severity.MEDIUM
        return v

    @field_validator("category", mode="before")
    @classmethod
    def _norm_category(cls, v):
        if isinstance(v, str):
            v = v.strip().lower()
            if v not in {c.value for c in Category}:
                return Category.MAINTAINABILITY
        return v

    def key(self) -> tuple[str, int, str]:
        return (self.file, self.line, self.title.strip().lower()[:40])

    def to_markdown(self) -> str:
        head = f"{self.severity.icon} **{self.title}** · `{self.severity.value}` · _{self.category.value}_"
        if self.rule:
            head += f" · `{self.source}:{self.rule}`"
        parts = [head]
        if self.body:
            parts.append(self.body.strip())
        if self.suggestion:
            parts.append("```suggestion\n" + self.suggestion.rstrip("\n") + "\n```")
        return "\n\n".join(parts)


class ReviewResult(BaseModel):
    findings: list[Finding] = Field(default_factory=list)
    summary: str = ""
    files_reviewed: int = 0
    provider: str = ""
    dropped: int = 0  # findings rejected because they didn't map to a changed line

    def counts(self) -> dict[str, int]:
        out = {s.value: 0 for s in Severity}
        for f in self.findings:
            out[f.severity.value] += 1
        return out

    def max_severity(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)
