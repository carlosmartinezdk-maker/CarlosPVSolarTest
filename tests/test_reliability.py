"""
Acceptance tests for the Reliability Engineering Addendum, first pass
(S12 life records + S13 distribution fitting). Separate file from
test_explorer_v2.py to avoid colliding with that file's own 34-49
numbering - these are new checks, not renumbered brief items.
Run from repo root: PYTHONPATH=. python3 tests/test_reliability.py
"""
import json
import os

import numpy as np
import openpyxl
import pandas as pd

import config

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_payload():
    path = os.path.join(REPO_ROOT, "explorer.html")
    with open(path) as f:
        html = f.read()
    marker = '<script type="application/json" id="payload-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_life_records_no_negative_duration():
    """Every life record's duration_years must be >= 0 - a negative value
    would mean an event was dated before the spell's own truncation/entry
    point, which S12's left-truncation logic is specifically built to
    prevent (age_start<0 episodes are quarantined before spells are built)."""
    life = pd.read_parquet(os.path.join(REPO_ROOT, "data/life_records.parquet"))
    bad = life[life["duration_years"] < 0]
    assert len(bad) == 0, f"{len(bad)} life records with negative duration_years"
    print(f"test (life records non-negative duration): passed, {len(life)} records checked")


def test_life_records_only_reliability_signatures():
    """S12 must only build life records for the 6 reliability-eligible
    signatures (config.RELIABILITY_SIGNATURES) - CURTAILMENT/SNOW/CLIPPING
    are exposure not unreliability, DEGRADATION is continuous (S7's job)."""
    life = pd.read_parquet(os.path.join(REPO_ROOT, "data/life_records.parquet"))
    bad_sigs = set(life["signature"].unique()) - config.RELIABILITY_SIGNATURES
    assert not bad_sigs, f"life records include non-reliability signatures: {bad_sigs}"
    print(f"test (life records signature scope): passed, {sorted(life['signature'].unique())}")


def test_min_failures_threshold_flagged():
    """Any signature fit on fewer failures than config.RELIABILITY
    min_failures_to_fit must carry below_min_failures_threshold=True, so a
    consumer of reliability_fits.json can't mistake a thin fit for a solid
    one."""
    with open(os.path.join(REPO_ROOT, "data/reliability_fits.json")) as f:
        fits = json.load(f)
    bad = [s["signature"] for s in fits["signatures"]
           if s["n_failures"] < config.RELIABILITY["min_failures_to_fit"] and not s["below_min_failures_threshold"]]
    assert not bad, f"signatures under the min-failures threshold not flagged: {bad}"
    print(f"test (min-failures flagging): passed, {len(fits['signatures'])} signatures checked")


def test_beta_below_one_never_rvm_eligible():
    """Hard rule (addendum): infant-mortality (beta<1) signatures must
    never be marked rvm_eligible - that framing is reserved for wear-out
    (beta>1) fits only."""
    with open(os.path.join(REPO_ROOT, "data/reliability_fits.json")) as f:
        fits = json.load(f)
    bad = [s["signature"] for s in fits["signatures"]
           if s["weibull_beta"] < 1.0 and s["rvm_eligible"]]
    assert not bad, f"beta<1 signatures incorrectly marked rvm_eligible: {bad}"
    print(f"test (beta<1 never RVM-eligible): passed, {len(fits['signatures'])} signatures checked")


def test_explorer_reliability_payload_present():
    """explorer.html's embedded payload carries a populated reliability
    block once S12/S13 have been run - not the 'not available' fallback."""
    payload = _load_payload()
    rel = payload.get("reliability")
    assert rel is not None, "payload missing 'reliability' key"
    assert rel["available"] is True, "reliability.available is False - S12/S13 output not found at build time"
    assert len(rel["signatures"]) == len(config.RELIABILITY_SIGNATURES), (
        f"expected {len(config.RELIABILITY_SIGNATURES)} signatures in payload, got {len(rel['signatures'])}")
    print(f"test (explorer reliability payload): passed, {len(rel['signatures'])} signatures embedded")


def test_41_conditional_probability_bounds():
    """Q(t0+t|t0) lies in [0,1] and is monotonically non-decreasing in t
    for every fitted signature (addendum test 41)."""
    forecast = pd.read_parquet(os.path.join(REPO_ROOT, "data/reliability_forecast.parquet"))
    bad_bounds = forecast[(forecast["cond_prob_failure"] < 0) | (forecast["cond_prob_failure"] > 1)]
    assert len(bad_bounds) == 0, f"{len(bad_bounds)} forecast rows outside [0,1]"
    n_checked = 0
    for (site, sig), g in forecast.groupby(["site", "signature"]):
        probs = g.sort_values("horizon_months")["cond_prob_failure"].to_numpy()
        assert np.all(np.diff(probs) >= -1e-9), f"non-monotonic forecast at {site}/{sig}: {probs}"
        n_checked += 1
    print(f"test 41 (conditional probability bounds): passed, {len(forecast)} rows / {n_checked} site-signature series checked")


def test_at_risk_excludes_mid_episode_sites():
    """A site currently mid-episode for a signature (no tail suspension
    after its last failure) must not appear in the forecast for that
    signature - it isn't at risk of STARTING a new episode while already
    in one (Section 6)."""
    life = pd.read_parquet(os.path.join(REPO_ROOT, "data/life_records.parquet"))
    forecast = pd.read_parquet(os.path.join(REPO_ROOT, "data/reliability_forecast.parquet"))
    last = life.sort_values("spell_index").groupby(["site", "signature"], as_index=False).tail(1)
    mid_episode = set(zip(last.loc[last["status"] == "F", "site"], last.loc[last["status"] == "F", "signature"]))
    forecast_pairs = set(zip(forecast["site"], forecast["signature"]))
    overlap = mid_episode & forecast_pairs
    assert not overlap, f"{len(overlap)} mid-episode site/signature pairs incorrectly forecast: {list(overlap)[:5]}"
    print(f"test (at-risk excludes mid-episode): passed, {len(mid_episode)} mid-episode pairs correctly excluded")


def test_workbook_reconciliation_gates_pass():
    """S17's Reconciliation tab gates must all read PASS before the
    workbook is delivered (addendum test 46) - a failing gate blocks
    delivery, not just a printed warning."""
    path = os.path.join(REPO_ROOT, "output/SSI_Solar_Reliability_Metrics.xlsx")
    wb = openpyxl.load_workbook(path, data_only=False)
    assert "Reconciliation" in wb.sheetnames, "workbook missing Reconciliation tab"
    ws = wb["Reconciliation"]
    fails = [row[0].value for row in ws.iter_rows(min_row=2) if row[3].value == "FAIL"]
    assert not fails, f"Reconciliation gate(s) failing: {fails}"
    expected_tabs = {"Notes", "Assumptions", "Fleet Summary", "Life Records", "Fits", "Hazard by Age",
                      "Forecast", "Spares Plan", "Inspection Schedule", "Warranty Value",
                      "Vintage Scorecard", "FMECA", "Benchmark", "Reconciliation"}
    missing = expected_tabs - set(wb.sheetnames)
    assert not missing, f"workbook missing tabs: {missing}"
    print(f"test (workbook reconciliation + tabs): passed, {len(wb.sheetnames)} sheets, all Reconciliation gates PASS")


if __name__ == "__main__":
    test_life_records_no_negative_duration()
    test_life_records_only_reliability_signatures()
    test_min_failures_threshold_flagged()
    test_beta_below_one_never_rvm_eligible()
    test_explorer_reliability_payload_present()
    test_41_conditional_probability_bounds()
    test_at_risk_excludes_mid_episode_sites()
    test_workbook_reconciliation_gates_pass()
