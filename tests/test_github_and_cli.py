import json

import httpx

from pr_sentinel.cli import main
from pr_sentinel.github import GitHubClient, PullRequest
from pr_sentinel.models import Finding, ReviewResult, Severity


def _result():
    return ReviewResult(provider="fake:x", files_reviewed=1, summary="Looks risky.", findings=[
        Finding(file="app/db.py", line=5, severity=Severity.CRITICAL, category="security",
                title="SQL injection", body="Use params.", suggestion="cur = conn.execute(q, (u,))"),
    ])


def test_pr_from_event(tmp_path):
    ev = tmp_path / "event.json"
    ev.write_text(json.dumps({
        "repository": {"full_name": "o/r"},
        "pull_request": {"number": 7, "head": {"sha": "abc"}, "title": "T", "body": None},
    }))
    gh = GitHubClient(token="t", client=httpx.Client())
    pr = gh.pr_from_event(str(ev))
    assert (pr.repo, pr.number, pr.head_sha, pr.title, pr.body) == ("o/r", 7, "abc", "T", "")


def test_post_review_payload():
    sent = []

    def handler(req):
        sent.append((req.url.path, json.loads(req.content)))
        return httpx.Response(200, json={"id": 1})

    gh = GitHubClient(token="t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    gh.post_review(PullRequest("o/r", 7, "abc"), _result())
    path, body = sent[0]
    assert path == "/repos/o/r/pulls/7/reviews"
    assert body["event"] == "COMMENT" and body["commit_id"] == "abc"
    c = body["comments"][0]
    assert (c["path"], c["line"], c["side"]) == ("app/db.py", 5, "RIGHT")
    assert "```suggestion" in c["body"]
    assert "<!-- pr-sentinel -->" in body["body"]


def test_post_review_falls_back_when_batch_rejected():
    calls = []

    def handler(req):
        calls.append(req.url.path)
        if req.url.path.endswith("/reviews") and len(calls) == 1:
            return httpx.Response(422, json={"message": "line must be part of the diff"})
        if req.url.path.endswith("/comments"):
            return httpx.Response(422)
        return httpx.Response(200, json={"id": 2})

    gh = GitHubClient(token="t", client=httpx.Client(transport=httpx.MockTransport(handler)))
    gh.post_review(PullRequest("o/r", 7, "abc"), _result())
    assert calls == ["/repos/o/r/pulls/7/reviews", "/repos/o/r/pulls/7/comments",
                     "/repos/o/r/pulls/7/reviews"]


def test_cli_review_json_and_fail_on(tmp_path, sample_diff, capsys):
    d = tmp_path / "x.diff"
    d.write_text(sample_diff)
    code = main(["review", "--diff-file", str(d), "--provider", "fake", "--no-static",
                 "--format", "json", "--fail-on", "high"])
    out = json.loads(capsys.readouterr().out)
    assert code == 1
    assert out["files_reviewed"] == 2 and out["findings"]


def test_cli_text_passes_without_fail_on(tmp_path, sample_diff, capsys):
    d = tmp_path / "x.diff"
    d.write_text(sample_diff)
    assert main(["review", "--diff-file", str(d), "--provider", "fake", "--no-static"]) == 0
    assert "Possible SQL injection" in capsys.readouterr().out


def test_cli_missing_key_is_clean_error(tmp_path, sample_diff, monkeypatch, capsys):
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    d = tmp_path / "x.diff"
    d.write_text(sample_diff)
    assert main(["review", "--diff-file", str(d), "--provider", "openai"]) == 2
    assert "OPENAI_API_KEY" in capsys.readouterr().err
