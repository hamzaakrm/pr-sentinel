from pr_sentinel.diff import nearest_commentable, parse_diff


def test_parses_files_and_flags(sample_diff):
    files = {f.path: f for f in parse_diff(sample_diff)}
    assert set(files) == {"app/db.py", "README.md", "yarn.lock", "logo.png"}
    assert files["logo.png"].is_binary
    assert files["app/db.py"].language == "python"


def test_new_file_line_numbers(sample_diff):
    db = next(f for f in parse_diff(sample_diff) if f.path == "app/db.py")
    assert db.additions == 9 and db.deletions == 3
    assert db.added_lines == set(range(4, 13))
    # context lines are commentable too, removed ones are not
    assert {1, 2, 3, 13, 14, 15} <= db.commentable_lines


def test_content_that_looks_like_headers_stays_in_hunk():
    diff = (
        "diff --git a/x.md b/x.md\n--- a/x.md\n+++ b/x.md\n@@ -1,2 +1,3 @@\n"
        " title\n+--- not a header\n++++ also content\n"
    )
    (f,) = parse_diff(diff)
    assert f.path == "x.md"
    texts = [ln.text for h in f.hunks for ln in h.lines if ln.kind == "+"]
    assert texts == ["--- not a header", "+++ also content"]


def test_new_and_renamed_files():
    diff = (
        "diff --git a/n.py b/n.py\nnew file mode 100644\n--- /dev/null\n+++ b/n.py\n"
        "@@ -0,0 +1,2 @@\n+a = 1\n+b = 2\n"
        "diff --git a/old.py b/new.py\nsimilarity index 90%\nrename from old.py\nrename to new.py\n"
        "--- a/old.py\n+++ b/new.py\n@@ -1 +1 @@\n-x\n+y\n"
    )
    n, r = parse_diff(diff)
    assert n.is_new and n.added_lines == {1, 2}
    assert r.path == "new.py" and r.old_path == "old.py"


def test_plain_unified_diff_without_git_header():
    diff = "--- a.py\t2024\n+++ a.py\t2024\n@@ -1 +1,2 @@\n x\n+y\n"
    (f,) = parse_diff(diff)
    assert f.path == "a.py" and f.added_lines == {2}


def test_render_for_llm_includes_line_numbers(sample_diff):
    db = next(f for f in parse_diff(sample_diff) if f.path == "app/db.py")
    text = db.render_for_llm()
    assert "   5 + " in text and "     - " in text


def test_nearest_commentable_snaps(sample_diff):
    db = next(f for f in parse_diff(sample_diff) if f.path == "app/db.py")
    assert nearest_commentable(db, 5) == 5
    assert nearest_commentable(db, 17) == 15
    assert nearest_commentable(db, 99) is None
