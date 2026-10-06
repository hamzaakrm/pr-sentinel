"""Unified diff parsing.

Turns `git diff` output into structured files/hunks and tracks which line numbers
in the *new* file were added. GitHub only accepts review comments on lines that
are part of the diff, so this mapping is what lets us reject hallucinated
line numbers from the LLM.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

HUNK_RE = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass
class DiffLine:
    kind: str  # "+", "-", " "
    text: str
    new_lineno: int | None  # None for removed lines
    old_lineno: int | None  # None for added lines


@dataclass
class Hunk:
    header: str
    new_start: int
    lines: list[DiffLine] = field(default_factory=list)


@dataclass
class FileDiff:
    path: str
    old_path: str | None = None
    is_new: bool = False
    is_deleted: bool = False
    is_binary: bool = False
    hunks: list[Hunk] = field(default_factory=list)

    @property
    def added_lines(self) -> set[int]:
        return {ln.new_lineno for h in self.hunks for ln in h.lines if ln.kind == "+" and ln.new_lineno}

    @property
    def commentable_lines(self) -> set[int]:
        """Lines on the RIGHT side of the diff (added or context) — valid anchors for GitHub."""
        return {
            ln.new_lineno for h in self.hunks for ln in h.lines if ln.kind in "+ " and ln.new_lineno
        }

    @property
    def additions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "+")

    @property
    def deletions(self) -> int:
        return sum(1 for h in self.hunks for ln in h.lines if ln.kind == "-")

    @property
    def language(self) -> str:
        ext = self.path.rsplit(".", 1)[-1].lower() if "." in self.path else ""
        return {
            "py": "python", "js": "javascript", "jsx": "javascript", "ts": "typescript",
            "tsx": "typescript", "java": "java", "go": "go", "rb": "ruby", "rs": "rust",
            "c": "c", "h": "c", "cpp": "cpp", "cs": "csharp", "php": "php", "kt": "kotlin",
            "swift": "swift", "sql": "sql", "sh": "bash", "yml": "yaml", "yaml": "yaml",
        }.get(ext, ext or "text")

    def render_for_llm(self) -> str:
        """Render hunks with explicit new-file line numbers so the model can cite them."""
        out = [f"### File: {self.path} ({self.language})"]
        for h in self.hunks:
            out.append(h.header)
            for ln in h.lines:
                if ln.kind == "-":
                    out.append(f"     - {ln.text}")
                else:
                    marker = "+" if ln.kind == "+" else " "
                    out.append(f"{ln.new_lineno:>4} {marker} {ln.text}")
        return "\n".join(out)


def _strip_prefix(p: str) -> str:
    p = p.strip()
    if p.startswith('"') and p.endswith('"'):
        p = p[1:-1]
    if p.startswith(("a/", "b/")):
        p = p[2:]
    return p


def parse_diff(text: str) -> list[FileDiff]:
    """Parse unified diff text (git or plain `diff -u`) into FileDiff objects.

    State machine: outside a hunk we read file headers; inside a hunk we consume
    exactly as many old/new lines as the @@ header promised, so content lines that
    happen to start with "--- " or "+++ " are never mistaken for headers.
    """
    files: list[FileDiff] = []
    cur: FileDiff | None = None
    hunk: Hunk | None = None
    old_no = new_no = old_left = new_left = 0

    for raw in text.splitlines():
        in_hunk = hunk is not None and (old_left > 0 or new_left > 0)

        if in_hunk:
            tag, body = (raw[0], raw[1:]) if raw else (" ", "")  # blank = stripped context line
            if tag == "+":
                hunk.lines.append(DiffLine("+", body, new_no, None))
                new_no += 1
                new_left -= 1
            elif tag == "-":
                hunk.lines.append(DiffLine("-", body, None, old_no))
                old_no += 1
                old_left -= 1
            elif tag == " ":
                hunk.lines.append(DiffLine(" ", body, new_no, old_no))
                old_no += 1
                new_no += 1
                old_left -= 1
                new_left -= 1
            # "\\ No newline at end of file" and anything else: ignore
            continue

        if raw.startswith("\\"):
            continue
        if raw.startswith("diff --git "):
            m = re.match(r"diff --git (\S+) (\S+)", raw)
            cur = FileDiff(path=_strip_prefix(m.group(2)) if m else raw.split()[-1])
            files.append(cur)
            hunk = None
            continue
        if raw.startswith("--- "):
            if cur is None or cur.hunks:  # plain diff -u: a new file starts here
                cur = FileDiff(path="")
                files.append(cur)
                hunk = None
            src_path = raw[4:].split("\t")[0]
            if src_path == "/dev/null":
                cur.is_new = True
            else:
                cur.old_path = _strip_prefix(src_path)
            continue
        if cur is None:
            continue
        if raw.startswith("+++ "):
            dst = raw[4:].split("\t")[0]
            if dst == "/dev/null":
                cur.is_deleted = True
                cur.path = cur.path or (cur.old_path or "")
            else:
                cur.path = _strip_prefix(dst)
            continue
        m = HUNK_RE.match(raw)
        if m:
            old_no, new_no = int(m.group(1)), int(m.group(3))
            old_left = int(m.group(2)) if m.group(2) is not None else 1
            new_left = int(m.group(4)) if m.group(4) is not None else 1
            hunk = Hunk(header=raw, new_start=new_no)
            cur.hunks.append(hunk)
            continue
        if raw.startswith("new file mode"):
            cur.is_new = True
        elif raw.startswith("deleted file mode"):
            cur.is_deleted = True
        elif raw.startswith(("Binary files", "GIT binary patch")):
            cur.is_binary = True
        elif raw.startswith("rename from "):
            cur.old_path = raw[len("rename from "):]
        elif raw.startswith("rename to "):
            cur.path = raw[len("rename to "):]

    return [f for f in files if f.path]


def nearest_commentable(fd: FileDiff, line: int, tolerance: int = 3) -> int | None:
    """Snap an LLM-cited line to the closest valid line (models are often off by one or two)."""
    valid = fd.commentable_lines
    if line in valid:
        return line
    best = None
    for cand in valid:
        d = abs(cand - line)
        if d <= tolerance and (best is None or d < abs(best - line)):
            best = cand
    return best
