"""Acceptance test 24: no code path references the pre-rename NREL domain.
Scans for the literal host string used as a URL/host value (not narrative
text in docstrings/report strings explaining the migration history)."""
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
LIVE_HOST_PATTERNS = [
    re.compile(r"https?://[^\s\"']*nrel\.gov"),
    re.compile(r'host\s*=\s*["\']\S*nrel\.gov'),
    re.compile(r'NSRDB_HOST\s*=\s*["\']\S*nrel\.gov'),
]


def test_no_live_nrel_gov_reference():
    hits = []
    for py_file in REPO_ROOT.glob("*.py"):
        text = py_file.read_text()
        for pattern in LIVE_HOST_PATTERNS:
            for m in pattern.finditer(text):
                hits.append(f"{py_file.name}: {m.group(0)}")
    assert hits == [], f"live nrel.gov host reference(s) found: {hits}"


if __name__ == "__main__":
    test_no_live_nrel_gov_reference()
    print("test 24 (no stale domain in code paths) passed")
