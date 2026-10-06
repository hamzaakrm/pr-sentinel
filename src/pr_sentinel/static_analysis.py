"""Deterministic static analysis on changed files.

Static tools are cheap, precise and never hallucinate, so they run first. Their
results are (a) posted directly as findings and (b) fed to the LLM as context so it
doesn't waste effort repeating them and can focus on logic-level issues.

Only findings on lines *added* in the diff are kept — we review the change, not
the whole legacy file.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

from .diff import FileDiff
from .models import Category, Finding, Severity

# Ruff rule prefixes worth surfacing in a review (skip pure formatting noise).
RUFF_SELECT = "F,E9,B,S,PLE,PERF"

# Bandit "blacklist import" checks (B4xx) fire on merely importing subprocess/pickle: too noisy.
BANDIT_SKIP_PREFIXES = ("B4",)

_BANDIT_SEV = {"LOW": Severity.LOW, "MEDIUM": Severity.MEDIUM, "HIGH": Severity.HIGH}


def _ruff_category(code: str) -> tuple[Category, Severity]:
    if code.startswith("S"):
        return Category.SECURITY, Severity.MEDIUM
    if code.startswith(("F8", "F6", "F7", "E9", "B")):
        return Category.BUG, Severity.MEDIUM
    if code.startswith("PERF"):
        return Category.PERFORMANCE, Severity.LOW
    return Category.MAINTAINABILITY, Severity.LOW


def run_ruff(paths: list[str], root: Path) -> list[Finding]:
    exe = shutil.which("ruff")
    if not exe or not paths:
        return []
    proc = subprocess.run(
        [exe, "check", "--select", RUFF_SELECT, "--output-format", "json", "--no-cache",
         "--exit-zero", *paths],
        cwd=root, capture_output=True, text=True, timeout=120, check=False,
    )
    try:
        items = json.loads(proc.stdout or "[]")
    except json.JSONDecodeError:
        return []
    out = []
    for it in items:
        code = it.get("code") or "ruff"
        cat, sev = _ruff_category(code)
        rel = _rel(it.get("filename", ""), root)
        fix = (it.get("fix") or {}).get("message")
        out.append(Finding(
            file=rel, line=max(1, it.get("location", {}).get("row", 1)), severity=sev,
            category=cat, title=it.get("message", code).split("\n")[0][:120],
            body=f"Fix: {fix}" if fix else "", source="ruff", rule=code,
        ))
    return out


def run_bandit(paths: list[str], root: Path) -> list[Finding]:
    exe = shutil.which("bandit")
    if not exe or not paths:
        return []
    proc = subprocess.run(
        [exe, "-f", "json", "-q", *paths],
        cwd=root, capture_output=True, text=True, timeout=120, check=False,
    )
    try:
        data = json.loads(proc.stdout or "{}")
    except json.JSONDecodeError:
        return []
    out = []
    for it in data.get("results", []):
        if str(it.get("test_id", "")).startswith(BANDIT_SKIP_PREFIXES):
            continue
        sev = _BANDIT_SEV.get(it.get("issue_severity", "MEDIUM"), Severity.MEDIUM)
        if it.get("issue_confidence") == "LOW" and sev.rank > Severity.LOW.rank:
            sev = Severity(["info", "low", "medium", "high", "critical"][sev.rank - 1])
        cwe = (it.get("issue_cwe") or {}).get("id")
        out.append(Finding(
            file=_rel(it.get("filename", ""), root), line=max(1, it.get("line_number", 1)),
            severity=sev, category=Category.SECURITY, title=it.get("issue_text", "")[:120],
            body=(f"CWE-{cwe}. " if cwe else "") + (it.get("more_info") or ""),
            source="bandit", rule=it.get("test_id"),
        ))
    return out


def _rel(path: str, root: Path) -> str:
    p = Path(path)
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix().lstrip("./")


def analyze(files: list[FileDiff], root: str | Path = ".") -> list[Finding]:
    """Run available static analyzers and keep only findings on added lines."""
    root = Path(root)
    by_path = {f.path: f for f in files}
    py = [f.path for f in files if f.language == "python" and not f.is_deleted
          and (root / f.path).is_file()]
    findings = run_ruff(py, root) + run_bandit(py, root)
    # Keep only added lines, and collapse ruff/bandit duplicates: ruff's flake8-bandit
    # rules reuse bandit's numbers (S501 == B501), so key on the shared number.
    best: dict[tuple[str, int, str], Finding] = {}
    for f in findings:
        fd = by_path.get(f.file)
        if not fd or f.line not in fd.added_lines:
            continue
        k = (f.file, f.line, _issue_id(f.rule or f.title))
        if k not in best or f.severity.rank > best[k].severity.rank:
            best[k] = f
    return list(best.values())


def _issue_id(rule: str) -> str:
    """S501 / B501 -> 'sec501'; anything else is its own id."""
    if len(rule) == 4 and rule[0] in "SB" and rule[1:].isdigit():
        return f"sec{rule[1:]}"
    return rule
