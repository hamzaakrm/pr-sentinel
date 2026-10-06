import json

from pr_sentinel.config import Config
from pr_sentinel.models import Severity
from pr_sentinel.prompt import extract_json, parse_findings
from pr_sentinel.providers import get_provider
from pr_sentinel.providers.base import LLMProvider
from pr_sentinel.review import ReviewEngine


class ScriptedProvider(LLMProvider):
    name = "scripted"

    def __init__(self, reply: str):
        super().__init__(model="x")
        self.reply = reply
        self.prompts: list[tuple[str, str]] = []

    def complete(self, system, user):
        self.prompts.append((system, user))
        return self.reply


def cfg(**kw):
    return Config(static_analysis=False, **kw)


def test_fake_provider_end_to_end(sample_diff):
    engine = ReviewEngine(get_provider("fake"), cfg())
    result = engine.review_diff(sample_diff)
    titles = {f.title for f in result.findings}
    assert "Possible SQL injection" in titles
    assert "Arbitrary code execution via eval/exec" in titles
    assert "Mutable default argument" in titles
    # ignored + binary files are skipped
    assert result.files_reviewed == 2
    # sorted most severe first
    ranks = [f.severity.rank for f in result.findings]
    assert ranks == sorted(ranks, reverse=True)


def test_hallucinated_lines_are_dropped_and_near_misses_snapped(sample_diff):
    reply = json.dumps({"summary": "s", "findings": [
        {"file": "app/db.py", "line": 5, "severity": "high", "title": "ok"},
        {"file": "./app/db.py", "line": 17, "severity": "high", "title": "snapped"},
        {"file": "app/db.py", "line": 400, "severity": "high", "title": "hallucinated"},
        {"file": "nope.py", "line": 1, "severity": "high", "title": "wrong file"},
        {"line": 3},
    ]})
    result = ReviewEngine(ScriptedProvider(reply), cfg()).review_diff(sample_diff)
    by_title = {f.title: f for f in result.findings}
    assert set(by_title) == {"ok", "snapped"}
    assert by_title["snapped"].line == 15 and by_title["snapped"].file == "app/db.py"
    assert result.dropped == 3


def test_min_severity_and_cap(sample_diff):
    engine = ReviewEngine(get_provider("fake"), cfg(min_severity=Severity.HIGH, max_comments=1))
    result = engine.review_diff(sample_diff)
    assert len(result.findings) == 1
    assert result.findings[0].severity == Severity.CRITICAL


def test_prompt_contains_numbered_diff_and_skips_ignored(sample_diff):
    p = ScriptedProvider('{"summary": "", "findings": []}')
    ReviewEngine(p, cfg(extra_instructions="Use Django idioms")).review_diff(
        sample_diff, pr_title="Refactor user lookup"
    )
    system, user = p.prompts[0]
    assert "Use Django idioms" in system
    assert "Refactor user lookup" in user
    assert "### File: app/db.py" in user
    assert "yarn.lock" not in user and "logo.png" not in user


def test_chunking_splits_large_diffs(sample_diff):
    p = ScriptedProvider('{"summary": "", "findings": []}')
    ReviewEngine(p, cfg(max_chunk_chars=50)).review_diff(sample_diff)
    assert len(p.prompts) == 2


def test_provider_failure_does_not_crash(sample_diff):
    result = ReviewEngine(ScriptedProvider("I cannot help with that"), cfg()).review_diff(sample_diff)
    assert result.findings == []


def test_extract_json_tolerates_fences_and_prose():
    assert extract_json('Sure!\n```json\n{"findings": []}\n```')["findings"] == []
    assert extract_json('blah {"summary": "x", "findings": []} trailing')["summary"] == "x"
    assert extract_json('[{"file": "a", "line": 1, "title": "t"}]')["findings"][0]["file"] == "a"


def test_parse_findings_normalises_fields():
    reply = json.dumps({"findings": [
        {"file": "a.py", "line": 2, "severity": "Warning", "category": "weird",
         "title": "t", "suggestion": "null"},
        "garbage",
    ]})
    _, found, bad = parse_findings(reply)
    assert bad == 1
    assert found[0].severity == Severity.MEDIUM
    assert found[0].category.value == "maintainability"
    assert found[0].suggestion is None


def test_unknown_provider():
    import pytest

    from pr_sentinel.providers import ProviderError

    with pytest.raises(ProviderError):
        get_provider("gpt-nonexistent")


def test_static_dedupe_merges_ruff_and_bandit(tmp_path):
    import shutil

    import pytest

    if not (shutil.which("ruff") and shutil.which("bandit")):
        pytest.skip("ruff/bandit not installed")
    from pr_sentinel.diff import parse_diff
    from pr_sentinel.static_analysis import analyze

    (tmp_path / "m.py").write_text(
        "import requests\n\n\ndef f():\n    return requests.get('https://x', verify=False, timeout=5)\n"
    )
    diff = "diff --git a/m.py b/m.py\n--- /dev/null\n+++ b/m.py\n@@ -0,0 +1,5 @@\n" + "".join(
        "+" + ln + "\n" for ln in (tmp_path / "m.py").read_text().splitlines()
    )
    found = analyze(parse_diff(diff), tmp_path)
    tls = [f for f in found if f.rule in ("S501", "B501")]
    assert len(tls) == 1 and tls[0].line == 5
