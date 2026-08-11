"""Acceptance tests 26, 27, 29 - run after the full S0-S9 chain has produced
its parquet outputs (see run_all.sh)."""
import os
import re

import pandas as pd

import config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_26_leap_day_rows():
    """2020 and 2024 NSRDB caches (Track A or B) must have 8,784 hourly
    rows, not 8,760 - the API/clear-sky path must include Feb 29."""
    cache_dir = os.path.join(REPO_ROOT, config.NSRDB_CACHE_DIR)
    if not os.path.isdir(cache_dir):
        print("test 26: skipped, no cache present")
        return
    checked = 0
    for root, _, files in os.walk(cache_dir):
        for f in files:
            if "year=2020" in root or "year=2024" in root:
                if f.startswith("weather_"):
                    df = pd.read_parquet(os.path.join(root, f))
                    assert len(df) == 8784, f"{root}/{f}: {len(df)} rows, expected 8784 (leap year)"
                    checked += 1
    print(f"test 26 (leap day): checked {checked} leap-year cache files")


def test_27_2026_no_pi():
    path = os.path.join(REPO_ROOT, "data", "site_month_indices.parquet")
    if not os.path.exists(path):
        print("test 27: skipped, site_month_indices.parquet not present")
        return
    df = pd.read_parquet(path)
    y2026 = df[df["year"] == 2026]
    if len(y2026) == 0:
        print("test 27: skipped, no 2026 rows in this run")
        return
    assert y2026["PI"].notna().sum() == 0, "2026 rows carry a non-null PI"
    assert y2026["PR_T"].notna().sum() == 0, "2026 rows carry a non-null PR_T"
    print(f"test 27 (2026 PI/PR_T null): passed on {len(y2026)} 2026 site-months")

    decision_path = os.path.join(REPO_ROOT, "data", "site_month_decision.parquet")
    if os.path.exists(decision_path):
        dd = pd.read_parquet(decision_path)
        bad = dd[(dd["year"] == 2026) & (dd["quadrant"] == "LEAD")]
        assert len(bad) == 0, "2026 site-month(s) carry a qualified LEAD flag"
        print("test 27b (no 2026 LEAD): passed")


def test_29_no_secrets_in_outputs():
    key = (os.environ.get(config.NSRDB_API_KEY_ENV_PRIMARY) or
           os.environ.get(config.NSRDB_API_KEY_ENV_FALLBACK) or "")
    if not key:
        print("test 29: skipped, no API key set in this environment")
        return
    hits = []
    data_dir = os.path.join(REPO_ROOT, "data")
    output_dir = os.path.join(REPO_ROOT, "output")
    for base in (data_dir, output_dir, REPO_ROOT):
        if not os.path.isdir(base):
            continue
        for root, dirs, files in os.walk(base):
            dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
            for f in files:
                if f.endswith((".parquet", ".csv", ".md", ".html", ".log", ".json")):
                    fp = os.path.join(root, f)
                    try:
                        if key in fp:
                            hits.append(f"filename: {fp}")
                        with open(fp, "rb") as fh:
                            if key.encode() in fh.read():
                                hits.append(f"content: {fp}")
                    except (UnicodeDecodeError, OSError):
                        pass
    assert hits == [], f"API key found in output(s): {hits}"
    print("test 29 (no secrets in outputs): passed")


if __name__ == "__main__":
    test_26_leap_day_rows()
    test_27_2026_no_pi()
    test_29_no_secrets_in_outputs()
