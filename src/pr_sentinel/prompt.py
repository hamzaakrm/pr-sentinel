"""Prompt construction and robust parsing of the model's JSON reply."""

from __future__ import annotations

import json
import re

from .diff import FileDiff
from .models import Finding

SYSTEM_PROMPT = """You are PR Sentinel, a meticulous senior software engineer reviewing a pull request.

Review ONLY the lines added in the diff (marked with `+`). Context lines are there to help you
understand the change. Each new-file line is prefixed with its line number; cite those numbers.

Focus areas, in priority order: {focus}.

Rules:
- Report real, specific problems: bugs, edge cases, security flaws, race conditions, resource
  leaks, incorrect error handling, performance traps, missing validation, misleading names.
- Do NOT report pure formatting, import order, or anything a linter already flagged (listed
  under "Static analysis already reported").
- Do NOT praise the code or restate what it does. No speculative "consider adding tests"
  comments unless a specific untested edge case is clearly risky.
- Prefer fewer, high-confidence findings. If the change looks fine, return an empty list.
- When a concrete fix fits in a few lines, put the full replacement for the cited line(s) in
  "suggestion" (code only, no fences). Otherwise use null.
- severity: critical (exploitable / data loss / crash in common path), high (likely bug),
  medium (bug in edge case or notable risk), low (minor improvement), info.
- category: bug | security | performance | style | maintainability | testing
{extra}
Respond with ONLY a JSON object, no prose, in exactly this shape:
{{
  "summary": "2-3 sentence overall assessment of the change",
  "findings": [
    {{"file": "path/as/shown", "line": 42, "severity": "high", "category": "bug",
      "title": "short headline", "body": "why it is a problem and how to fix it",
      "suggestion": "replacement code or null"}}
  ]
}}"""


def build_system_prompt(focus: list[str], extra: str = "") -> str:
    extra_block = f"\nProject-specific instructions:\n{extra.strip()}\n" if extra.strip() else ""
    return SYSTEM_PROMPT.format(focus=", ".join(focus), extra=extra_block)


def build_user_prompt(files: list[FileDiff], static: list[Finding], pr_title: str = "",
                      pr_body: str = "") -> str:
    parts = []
    if pr_title:
        parts.append(f"## Pull request: {pr_title}")
    if pr_body:
        parts.append(f"Description:\n{pr_body.strip()[:2000]}")
    paths = {f.path for f in files}
    relevant = [s for s in static if s.file in paths]
    if relevant:
        parts.append("## Static analysis already reported (do not repeat):")
        parts.extend(f"- {s.file}:{s.line} [{s.rule}] {s.title}" for s in relevant)
    parts.append("## Diff")
    parts.extend(f.render_for_llm() for f in files)
    return "\n\n".join(parts)


def chunk_files(files: list[FileDiff], max_chars: int) -> list[list[FileDiff]]:
    """Greedy bin-packing of files into prompt-sized chunks."""
    chunks: list[list[FileDiff]] = []
    cur: list[FileDiff] = []
    size = 0
    for f in files:
        n = len(f.render_for_llm())
        if cur and size + n > max_chars:
            chunks.append(cur)
            cur, size = [], 0
        cur.append(f)
        size += n
    if cur:
        chunks.append(cur)
    return chunks


_FENCE_RE = re.compile(r"```(?:json)?\s*(.*?)```", re.S)


def extract_json(text: str) -> dict:
    """Pull a JSON object out of a model reply, tolerating fences and stray prose."""
    text = text.strip()
    candidates = [text]
    candidates += _FENCE_RE.findall(text)
    if "{" in text and "}" in text:
        candidates.append(text[text.index("{"): text.rindex("}") + 1])
    for c in candidates:
        try:
            obj = json.loads(c)
        except json.JSONDecodeError:
            continue
        if isinstance(obj, list):
            return {"summary": "", "findings": obj}
        if isinstance(obj, dict):
            return obj
    raise ValueError(f"Model reply was not valid JSON: {text[:300]!r}")


def parse_findings(reply: str) -> tuple[str, list[Finding], int]:
    """Return (summary, valid findings, number of malformed findings skipped)."""
    data = extract_json(reply)
    raw = data.get("findings") or data.get("comments") or []
    out, bad = [], 0
    for item in raw if isinstance(raw, list) else []:
        if not isinstance(item, dict):
            bad += 1
            continue
        if isinstance(item.get("suggestion"), str) and item["suggestion"].strip().lower() in (
            "null", "none", ""
        ):
            item["suggestion"] = None
        try:
            item.setdefault("source", "llm")
            out.append(Finding(**{k: v for k, v in item.items() if k in Finding.model_fields}))
        except Exception:
            bad += 1
    return str(data.get("summary", "")).strip(), out, bad
