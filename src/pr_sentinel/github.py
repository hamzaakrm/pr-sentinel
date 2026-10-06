"""GitHub integration: read the PR from the Actions event, post a review with inline comments."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass

import httpx

from .models import Finding, ReviewResult
from .render import MARKER, summary_markdown

log = logging.getLogger("pr_sentinel")


@dataclass
class PullRequest:
    repo: str
    number: int
    head_sha: str
    title: str = ""
    body: str = ""


class GitHubClient:
    def __init__(self, token: str | None = None, api_url: str | None = None,
                 client: httpx.Client | None = None):
        token = token or os.environ.get("GITHUB_TOKEN")
        if not token:
            raise RuntimeError("GITHUB_TOKEN is not set")
        self.api = (api_url or os.environ.get("GITHUB_API_URL") or "https://api.github.com").rstrip("/")
        self.http = client or httpx.Client(timeout=60)
        self.headers = {"Authorization": f"Bearer {token}",
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28"}

    def pr_from_event(self, event_path: str | None = None) -> PullRequest:
        event_path = event_path or os.environ.get("GITHUB_EVENT_PATH")
        if not event_path:
            raise RuntimeError("GITHUB_EVENT_PATH is not set — are you running inside Actions?")
        with open(event_path) as fh:
            event = json.load(fh)
        pr = event.get("pull_request")
        if not pr:
            raise RuntimeError("This event has no pull_request payload")
        return PullRequest(repo=event["repository"]["full_name"], number=pr["number"],
                           head_sha=pr["head"]["sha"], title=pr.get("title") or "",
                           body=pr.get("body") or "")

    def get_diff(self, pr: PullRequest) -> str:
        r = self.http.get(f"{self.api}/repos/{pr.repo}/pulls/{pr.number}",
                          headers={**self.headers, "Accept": "application/vnd.github.v3.diff"})
        r.raise_for_status()
        return r.text

    def post_review(self, pr: PullRequest, result: ReviewResult) -> dict:
        comments = [self._comment(f) for f in result.findings]
        payload = {"commit_id": pr.head_sha, "event": "COMMENT",
                   "body": summary_markdown(result), "comments": comments}
        url = f"{self.api}/repos/{pr.repo}/pulls/{pr.number}/reviews"
        r = self.http.post(url, headers=self.headers, json=payload)
        if r.status_code == 422 and comments:
            # GitHub rejects the whole review if any single comment can't be placed.
            # Fall back to posting comments one by one, folding failures into the summary.
            log.warning("batch review rejected (%s); retrying per-comment", r.text[:200])
            return self._post_individually(pr, result, url)
        r.raise_for_status()
        return r.json()

    def _post_individually(self, pr: PullRequest, result: ReviewResult, url: str) -> dict:
        failed: list[Finding] = []
        for f in result.findings:
            r = self.http.post(f"{self.api}/repos/{pr.repo}/pulls/{pr.number}/comments",
                               headers=self.headers,
                               json={"commit_id": pr.head_sha, **self._comment(f)})
            if r.status_code >= 400:
                failed.append(f)
        r = self.http.post(url, headers=self.headers,
                           json={"commit_id": pr.head_sha, "event": "COMMENT",
                                 "body": summary_markdown(result, not_inlined=failed)})
        r.raise_for_status()
        return r.json()

    @staticmethod
    def _comment(f: Finding) -> dict:
        return {"path": f.file, "line": f.line, "side": "RIGHT", "body": f.to_markdown()}


__all__ = ["GitHubClient", "PullRequest", "MARKER"]
