from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_diff() -> str:
    return (FIXTURES / "sample.diff").read_text()


@pytest.fixture(autouse=True)
def _isolate(monkeypatch, tmp_path):
    """Run every test in an empty dir so the repo's own .pr-sentinel.yml isn't picked up."""
    monkeypatch.chdir(tmp_path)
    for var in ("PR_SENTINEL_PROVIDER", "PR_SENTINEL_MODEL", "PR_SENTINEL_MIN_SEVERITY",
                "PR_SENTINEL_FAIL_ON", "PR_SENTINEL_MAX_COMMENTS"):
        monkeypatch.delenv(var, raising=False)
