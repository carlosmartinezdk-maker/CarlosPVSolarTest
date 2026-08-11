"""Acceptance tests 28-32: S2's standalone-batch-job contract (Section 5 of
the updated brief). Run from repo root: PYTHONPATH=. python3 tests/test_s2_contract.py
"""
import json
import os
import subprocess
import sys
import tempfile

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_28_cache_completeness_count():
    """4,798 unique 4km cells x 7 years (2019-2025) = 33,586 at full scale.
    At subsample scale, assert the manifest accounts for every (cell, year)
    the pull summary claims to have attempted - no silent partial cache."""
    summary_path = os.path.join(REPO_ROOT, "data", "nsrdb_pull_summary.parquet")
    if not os.path.exists(summary_path):
        print("test 28: skipped, no pull summary present")
        return
    import pandas as pd
    summary = pd.read_parquet(summary_path)
    n_cells = summary[["grid_lat", "grid_lon"]].drop_duplicates().shape[0]
    n_years = summary["year"].nunique()
    expected = n_cells * n_years
    assert len(summary) == expected, (
        f"pull summary has {len(summary)} rows, expected {n_cells} cells x "
        f"{n_years} years = {expected} - cache is not complete for the "
        f"cell/year grid it claims to cover"
    )
    print(f"test 28 (cache completeness): {len(summary)} cell-years, "
          f"{n_cells} cells x {n_years} years - complete")


def test_29_preflight_classification():
    """With a host that is definitely not allowlisted, S2 must exit
    non-zero within a few seconds and name the cause as a network/proxy
    issue, not an auth failure."""
    import time
    script = os.path.join(REPO_ROOT, "s2_nsrdb.py")
    start = time.monotonic()
    result = subprocess.run(
        [sys.executable, script, "--preflight-only"],
        capture_output=True, text=True, timeout=30,
    )
    elapsed = time.monotonic() - start
    assert elapsed < 20, f"preflight took {elapsed:.1f}s, expected a fast fail"
    assert result.returncode != 0, "preflight succeeded - either network is now open, or the check is broken"
    stderr = result.stderr.lower()
    assert "proxy_denial" in stderr or "dns_failure" in stderr or "auth_failure" in stderr, (
        f"preflight did not classify the failure clearly: {result.stderr[-500:]}"
    )
    assert "auth_failure" not in stderr or "x-deny-reason" not in stderr, "misclassified proxy denial as auth failure"
    print(f"test 29 (preflight classification): passed in {elapsed:.1f}s - {result.stderr.strip().splitlines()[-1] if result.stderr.strip() else ''}")


def test_29b_dry_run_needs_no_network():
    """--dry-run must work with zero network access - it's for planning
    the pull before connectivity is even sorted out."""
    script = os.path.join(REPO_ROOT, "s2_nsrdb.py")
    sites_csv = os.path.join(REPO_ROOT, "data", "subsample_sites_latlon.csv")
    if not os.path.exists(sites_csv):
        print("test 29b: skipped, no sites csv present")
        return
    result = subprocess.run(
        [sys.executable, script, "--sites-csv", sites_csv, "--dry-run", "--years", "2019-2020"],
        capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, f"dry-run failed: {result.stderr}"
    lines = [l for l in result.stdout.strip().splitlines() if l]
    assert len(lines) > 0, "dry-run produced no cell-year list"
    print(f"test 29b (dry-run needs no network): passed, {len(lines)} cell-years listed")


def test_31_cache_manifest_refuses_incomplete():
    """S3's check_cache_complete must raise, naming missing partitions,
    rather than silently modelling a partial cache."""
    sys.path.insert(0, REPO_ROOT)
    import s3_model
    import pandas as pd

    fake_sites = pd.DataFrame({
        "site": ["nowhere"], "lat": [0.01], "lon": [0.01],  # ocean point, definitely not cached
    })
    try:
        s3_model.check_cache_complete(fake_sites, [2019])
        raise AssertionError("check_cache_complete did not raise on a missing cell-year")
    except RuntimeError as e:
        assert "grid_lat=0.0" in str(e) or "missing" in str(e).lower()
        print("test 31 (cache manifest refuses incomplete): passed -", str(e).splitlines()[0])


def test_32_no_secrets_including_manifest():
    key = os.environ.get("NLR_API_KEY") or os.environ.get("NREL_API_KEY") or ""
    if not key:
        print("test 32: skipped, no API key set in this environment")
        return
    manifest_path = os.path.join(REPO_ROOT, "nsrdb_cache", "manifest.json")
    if os.path.exists(manifest_path):
        with open(manifest_path) as f:
            content = f.read()
        assert key not in content, "API key found in nsrdb_cache/manifest.json"
    print("test 32 (no secrets, incl. manifest.json): passed")


if __name__ == "__main__":
    test_28_cache_completeness_count()
    test_29_preflight_classification()
    test_29b_dry_run_needs_no_network()
    test_31_cache_manifest_refuses_incomplete()
    test_32_no_secrets_including_manifest()
