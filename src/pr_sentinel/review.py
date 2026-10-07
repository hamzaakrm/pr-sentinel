"""Review engine: diff -> static analysis -> LLM -> validated, ranked findings."""

from __future__ import annotations

import logging
from concurrent.futures import ThreadPoolExecutor

from .config import Config
from .diff import FileDiff, nearest_commentable, parse_diff
from .models import Finding, ReviewResult
from .prompt import build_system_prompt, build_user_prompt, chunk_files, parse_findings
from .providers import LLMProvider, ProviderError
from .static_analysis import analyze

log = logging.getLogger("pr_sentinel")


class ReviewEngine:
    def __init__(self, provider: LLMProvider, config: Config, repo_root: str = "."):
        self.provider = provider
        self.config = config
        self.repo_root = repo_root

    def select_files(self, files: list[FileDiff]) -> list[FileDiff]:
        keep = [
            f for f in files
            if not (f.is_binary or f.is_deleted or not f.hunks or f.additions == 0
                    or self.config.is_ignored(f.path))
        ]
        # Review the biggest changes first if we have to cap.
        keep.sort(key=lambda f: f.additions, reverse=True)
        return keep[: self.config.max_files]

    def review_diff(self, diff_text: str, pr_title: str = "", pr_body: str = "") -> ReviewResult:
        files = self.select_files(parse_diff(diff_text))
        result = ReviewResult(files_reviewed=len(files), provider=repr(self.provider))
        if not files:
            result.summary = "No reviewable changes (only ignored, binary or deleted files)."
            return result

        static = analyze(files, self.repo_root) if self.config.static_analysis else []
        log.info("static analysis: %d finding(s)", len(static))

        system = build_system_prompt(self.config.focus, self.config.extra_instructions)
        chunks = chunk_files(files, self.config.max_chunk_chars)

        def run(chunk: list[FileDiff]):
            user = build_user_prompt(chunk, static, pr_title, pr_body)
            try:
                return chunk, *parse_findings(self.provider.complete(system, user))
            except (ProviderError, ValueError) as e:
                log.warning("chunk failed: %s", e)
                return chunk, "", [], str(e)

        with ThreadPoolExecutor(max_workers=min(4, len(chunks))) as pool:
            outputs = list(pool.map(run, chunks))

        llm_findings: list[Finding] = []
        summaries = []
        for chunk, summary, found, bad in outputs:
            if isinstance(bad, str):  # the LLM call for this chunk failed
                result.errors.append(bad[:500])
                continue
            if summary:
                summaries.append(summary)
            valid, dropped = self._anchor(found, chunk)
            llm_findings += valid
            result.dropped += dropped + bad

        result.findings = self._merge(static, llm_findings)
        if result.errors and not summaries:
            result.summary = "⚠️ The AI review failed, so only static-analysis results are shown."
        else:
            result.summary = " ".join(summaries) or "Review complete."
        return result

    @staticmethod
    def _anchor(findings: list[Finding], chunk: list[FileDiff]) -> tuple[list[Finding], int]:
        """Reject findings whose file/line aren't in the diff; snap near-misses."""
        by_path = {f.path: f for f in chunk}
        by_name: dict[str, FileDiff] = {}
        for f in chunk:
            by_name.setdefault(f.path.rsplit("/", 1)[-1], f)
        valid, dropped = [], 0
        for fnd in findings:
            path = fnd.file.strip().lstrip("./")
            fd = by_path.get(path) or by_path.get(path.removeprefix("b/")) or by_name.get(
                path.rsplit("/", 1)[-1]
            )
            line = nearest_commentable(fd, fnd.line) if fd else None
            if fd is None or line is None:
                dropped += 1
                continue
            valid.append(fnd.model_copy(update={"file": fd.path, "line": line}))
        return valid, dropped

    def _merge(self, static: list[Finding], llm: list[Finding]) -> list[Finding]:
        seen: set = set()
        static_spots = {(s.file, s.line, s.category) for s in static}
        merged = []
        for f in static + llm:
            if f.source == "llm" and (f.file, f.line, f.category) in static_spots:
                continue  # the linter already said it, more precisely
            if f.key() in seen:
                continue
            seen.add(f.key())
            if f.severity.rank >= self.config.min_severity.rank:
                merged.append(f)
        merged.sort(key=lambda f: (-f.severity.rank, f.file, f.line))
        return merged[: self.config.max_comments]
