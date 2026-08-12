"""Acceptance tests 34, 36, 37 from EXPLORER_V2_IMPROVEMENTS.md Part I -
run after s11_explorer.py has written explorer.html. Tests 35, 38-49 are
not yet applicable: they check quadrant routing, the map, pricing/RVM and
owner rollups, none of which are built yet (Parts C/E/F/D of the same
brief). Run from repo root: PYTHONPATH=. python3 tests/test_explorer_v2.py
"""
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_payload():
    path = os.path.join(REPO_ROOT, "explorer.html")
    with open(path) as f:
        html = f.read()
    marker = '<script type="application/json" id="payload-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_34_latest_scored():
    """No site has null latest_pi where at least one PI-scored month
    exists, and every such site has latest_scored_month set. latest_pri is
    read from that same latest-scored-by-PI month, so it can legitimately
    be null there even if the site has PRI elsewhere - only 12.6% of
    site-months are peer-benchmarked at subsample scale (A3), a separate,
    documented data-sparsity fact, not the A1 bug this test targets."""
    payload = _load_payload()
    bad = []
    pri_covered = 0
    for s in payload["sites"]:
        has_scored_pi = any(p is not None for p in s["pi"])
        if has_scored_pi and s["latest_pi"] is None:
            bad.append(s["site"] + " (null latest_pi)")
        if has_scored_pi and s["latest_scored_month"] is None:
            bad.append(s["site"] + " (missing latest_scored_month)")
        if s["latest_pri"] is not None:
            pri_covered += 1
    assert not bad, f"latest-scored violations: {bad}"
    print(f"test 34 (latest-scored): passed, {len(payload['sites'])} sites checked, "
          f"{pri_covered} with a non-null latest_pri")


def test_36_tier_consistency():
    """No site is 'Healthy' while carrying recoverable_usd_yr > 0 or
    excess_category = accelerating_loss."""
    payload = _load_payload()
    bad = [s["site"] for s in payload["sites"]
           if s["conviction_tier"] == "Healthy"
           and ((s["recoverable_usd_yr"] or 0) > 0 or s["excess_category"] == "accelerating_loss")]
    assert not bad, f"Healthy sites with recoverable value or accelerating_loss: {bad}"
    print(f"test 36 (tier consistency): passed, {len(payload['sites'])} sites checked")


def test_37_slope_gating():
    """No conviction tier of 'Improving' is driven by a beta with
    |beta_t| < BETA_T_SIGNIFICANCE_THRESHOLD (config.py)."""
    import config
    payload = _load_payload()
    bad = []
    for s in payload["sites"]:
        if s["conviction_tier"] == "Improving":
            if s["beta_t"] is None or abs(s["beta_t"]) < config.BETA_T_SIGNIFICANCE_THRESHOLD:
                bad.append((s["site"], s["beta_t"]))
    assert not bad, f"Improving sites with a non-significant beta_t: {bad}"
    print(f"test 37 (slope gating): passed, "
          f"{sum(1 for s in payload['sites'] if s['conviction_tier']=='Improving')} Improving sites checked")


if __name__ == "__main__":
    test_34_latest_scored()
    test_36_tier_consistency()
    test_37_slope_gating()
