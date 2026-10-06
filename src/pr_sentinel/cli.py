"""Command-line interface.

    pr-sentinel review                 # review uncommitted changes vs HEAD
    pr-sentinel review --base main     # review your branch against main
    pr-sentinel review --diff-file x.diff --format markdown
    pr-sentinel github                 # inside GitHub Actions: review the PR and post comments
"""

from __future__ import annotations

import argparse
import logging
import subprocess
import sys

from . import __version__
from .config import load_config
from .models import ReviewResult, Severity
from .providers import ProviderError, get_provider
from .render import to_json, to_markdown, to_text
from .review import ReviewEngine


def _git_diff(base: str | None, staged: bool) -> str:
    cmd = ["git", "diff", "--no-color", "--unified=3"]
    if staged:
        cmd.append("--cached")
    elif base:
        cmd.append(f"{base}...HEAD")
    else:
        cmd.append("HEAD")
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"git diff failed: {proc.stderr.strip()}")
    return proc.stdout


def _common(p: argparse.ArgumentParser) -> None:
    p.add_argument("--provider", help="anthropic | openai | ollama | fake")
    p.add_argument("--model", help="model name for the provider")
    p.add_argument("--config", help="path to .pr-sentinel.yml")
    p.add_argument("--min-severity", choices=[s.value for s in Severity])
    p.add_argument("--fail-on", choices=[s.value for s in Severity],
                   help="exit 1 if any finding is at or above this severity")
    p.add_argument("--no-static", action="store_true", help="skip ruff/bandit")
    p.add_argument("-v", "--verbose", action="store_true")


def _engine(args) -> ReviewEngine:
    overrides = {"provider": args.provider, "model": args.model,
                 "min_severity": args.min_severity, "fail_on": args.fail_on}
    if args.no_static:
        overrides["static_analysis"] = False
    cfg = load_config(args.config, **overrides)
    provider = get_provider(cfg.provider, model=cfg.model, temperature=cfg.temperature)
    return ReviewEngine(provider, cfg)


def _exit_code(engine: ReviewEngine, result: ReviewResult) -> int:
    fail_on, worst = engine.config.fail_on, result.max_severity()
    return 1 if fail_on and worst and worst.rank >= fail_on.rank else 0


def cmd_review(args) -> int:
    engine = _engine(args)
    if args.diff_file == "-":
        diff = sys.stdin.read()
    elif args.diff_file:
        with open(args.diff_file) as fh:
            diff = fh.read()
    else:
        diff = _git_diff(args.base, args.staged)
    if not diff.strip():
        print("Nothing to review: the diff is empty.")
        return 0
    result = engine.review_diff(diff)
    out = {"text": to_text, "markdown": to_markdown, "json": to_json}[args.format](result)
    print(out)
    return _exit_code(engine, result)


def cmd_github(args) -> int:
    from .github import GitHubClient

    engine = _engine(args)
    gh = GitHubClient()
    pr = gh.pr_from_event()
    result = engine.review_diff(gh.get_diff(pr), pr_title=pr.title, pr_body=pr.body)
    print(to_text(result, color=False))
    if args.dry_run:
        print("\n--dry-run: not posting to GitHub")
    else:
        gh.post_review(pr, result)
        print(f"\nPosted review with {len(result.findings)} comment(s) to {pr.repo}#{pr.number}")
    return _exit_code(engine, result)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pr-sentinel", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--version", action="version", version=f"pr-sentinel {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    r = sub.add_parser("review", help="review a local diff")
    src = r.add_mutually_exclusive_group()
    src.add_argument("--base", help="compare HEAD against this ref (e.g. main)")
    src.add_argument("--staged", action="store_true", help="review staged changes")
    src.add_argument("--diff-file", help="read a unified diff from a file ('-' for stdin)")
    r.add_argument("--format", choices=["text", "markdown", "json"], default="text")
    _common(r)
    r.set_defaults(func=cmd_review)

    g = sub.add_parser("github", help="review the current PR inside GitHub Actions")
    g.add_argument("--dry-run", action="store_true", help="print the review without posting")
    _common(g)
    g.set_defaults(func=cmd_github)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING,
                        format="%(levelname)s %(message)s")
    try:
        return args.func(args)
    except (ProviderError, RuntimeError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
