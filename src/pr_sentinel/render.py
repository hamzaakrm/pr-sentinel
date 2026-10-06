"""Output formatting for terminal, Markdown and JSON."""

from __future__ import annotations

import json
import sys

from .models import Finding, ReviewResult

MARKER = "<!-- pr-sentinel -->"

_COLORS = {"critical": "\033[1;31m", "high": "\033[31m", "medium": "\033[33m",
           "low": "\033[36m", "info": "\033[37m"}
_RESET, _DIM, _BOLD = "\033[0m", "\033[2m", "\033[1m"


def to_text(result: ReviewResult, color: bool | None = None) -> str:
    color = sys.stdout.isatty() if color is None else color
    c = (lambda code, s: f"{code}{s}{_RESET}") if color else (lambda code, s: s)
    lines = [c(_BOLD, f"PR Sentinel review — {result.provider}"),
             f"Files reviewed: {result.files_reviewed}   Findings: {len(result.findings)}", ""]
    for f in result.findings:
        sev = c(_COLORS[f.severity.value], f"[{f.severity.value.upper():8}]")
        src = f" ({f.source}:{f.rule})" if f.rule else ""
        lines.append(f"{sev} {f.file}:{f.line}  {c(_BOLD, f.title)}{c(_DIM, src)}")
        if f.body:
            lines += [f"           {ln}" for ln in f.body.strip().splitlines()]
        if f.suggestion:
            lines.append(c(_DIM, "           suggestion:"))
            lines += [c("\033[32m", f"             {ln}") for ln in f.suggestion.splitlines()]
        lines.append("")
    lines.append(c(_BOLD, "Summary: ") + result.summary)
    return "\n".join(lines)


def summary_markdown(result: ReviewResult, not_inlined: list[Finding] | None = None) -> str:
    counts = result.counts()
    badges = " · ".join(f"{n} {sev}" for sev, n in reversed(counts.items()) if n) or "no issues"
    md = [MARKER, "## 🛡️ PR Sentinel review", "", result.summary, "",
          f"**{len(result.findings)} finding(s):** {badges}  ",
          f"<sub>{result.files_reviewed} file(s) reviewed · model `{result.provider}`"
          + (f" · {result.dropped} unanchored comment(s) discarded" if result.dropped else "")
          + "</sub>"]
    if result.findings:
        md += ["", "| Severity | Location | Issue | Source |", "|---|---|---|---|"]
        for f in result.findings:
            src = f"{f.source}:{f.rule}" if f.rule else f.source
            title = f.title.replace("|", "\\|")
            md.append(f"| {f.severity.icon} {f.severity.value} | `{f.file}:{f.line}` | {title} | {src} |")
    if not_inlined:
        md += ["", "<details><summary>Comments that could not be placed inline</summary>", ""]
        for f in not_inlined:
            md += [f"**`{f.file}:{f.line}`**", "", f.to_markdown(), ""]
        md.append("</details>")
    md += ["", "<sub>AI-generated review. Verify suggestions before applying.</sub>"]
    return "\n".join(md)


def to_markdown(result: ReviewResult) -> str:
    out = [summary_markdown(result), ""]
    for f in result.findings:
        out += [f"### `{f.file}:{f.line}`", "", f.to_markdown(), ""]
    return "\n".join(out)


def to_json(result: ReviewResult) -> str:
    return json.dumps(result.model_dump(mode="json"), indent=2)
