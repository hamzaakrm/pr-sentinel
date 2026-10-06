"""Offline heuristic provider.

Used by the test-suite and for demos without an API key. It parses the same prompt
the real models receive and answers with the same JSON contract, so the whole
pipeline (validation, line snapping, posting) is exercised end-to-end.
It is deliberately simple pattern matching — not a substitute for a real model.
"""

from __future__ import annotations

import json
import re

from .base import LLMProvider

LINE_RE = re.compile(r"^\s*(\d+) \+ (.*)$")
FILE_RE = re.compile(r"^### File: (\S+)")

RULES: list[tuple[re.Pattern, dict]] = [
    (re.compile(r"\b(eval|exec)\s*\("), dict(
        severity="critical", category="security", title="Arbitrary code execution via eval/exec",
        body="Evaluating dynamic input can execute attacker-controlled code. "
             "Use `ast.literal_eval` or an explicit parser.")),
    (re.compile(r"(execute|query)\s*\(\s*f[\"']|(execute|query)\s*\(.*%\s*\(|"
                r"(execute|query)\s*\(.*\+\s*\w"), dict(
        severity="critical", category="security", title="Possible SQL injection",
        body="The query is built with string formatting. Use parameterised queries.")),
    (re.compile(r"except\s*:\s*$|except\s+Exception\s*:\s*pass"), dict(
        severity="medium", category="bug", title="Exception silently swallowed",
        body="A bare/broad `except` hides real failures. Catch specific exceptions and log them.")),
    (re.compile(r"==\s*None|!=\s*None"), dict(
        severity="low", category="style", title="Compare to None with `is`",
        body="Use `is None` / `is not None`; `==` can be overridden by `__eq__`.")),
    (re.compile(r"(password|secret|api_key|token)\s*=\s*[\"'][^\"']{4,}[\"']", re.I), dict(
        severity="high", category="security", title="Hard-coded credential",
        body="Secrets in source control leak. Load from environment or a secrets manager.")),
    (re.compile(r"def \w+\(.*=\s*(\[\]|\{\})"), dict(
        severity="medium", category="bug", title="Mutable default argument",
        body="The default is shared between calls. Use `None` and create it inside the function.")),
    (re.compile(r"verify\s*=\s*False"), dict(
        severity="high", category="security", title="TLS verification disabled",
        body="`verify=False` allows man-in-the-middle attacks.")),
    (re.compile(r"for .* in range\(len\("), dict(
        severity="low", category="maintainability", title="Iterate directly instead of range(len())",
        body="Use `enumerate()` or iterate the sequence directly.")),
]


class FakeProvider(LLMProvider):
    name = "fake"
    default_model = "heuristic-v1"

    def complete(self, system: str, user: str) -> str:
        findings, current = [], None
        for line in user.splitlines():
            if m := FILE_RE.match(line):
                current = m.group(1)
                continue
            if current and (m := LINE_RE.match(line)):
                lineno, code = int(m.group(1)), m.group(2)
                for pat, info in RULES:
                    if pat.search(code):
                        findings.append({"file": current, "line": lineno, **info})
                        break
        summary = (f"Heuristic review found {len(findings)} potential issue(s)."
                   if findings else "No issues detected by the heuristic reviewer.")
        return json.dumps({"summary": summary, "findings": findings})
