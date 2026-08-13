"""
Acceptance tests for the Reliability Engineering Addendum, first pass
(S12 life records + S13 distribution fitting). Separate file from
test_explorer_v2.py to avoid colliding with that file's own 34-49
numbering - these are new checks, not renumbered brief items.
Run from repo root: PYTHONPATH=. python3 tests/test_reliability.py
"""
import json
import os

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


if __name__ == "__main__":
    test_life_records_no_negative_duration()
    test_life_records_only_reliability_signatures()
    test_min_failures_threshold_flagged()
    test_beta_below_one_never_rvm_eligible()
    test_explorer_reliability_payload_present()
