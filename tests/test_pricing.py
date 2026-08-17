"""
Pricing correctness (CEO_COCKPIT_REVISIONS_PASS2.md Part B3): pricing.yaml
is the single source of truth for SaaS/SCADA rates - explorer.html,
ceo_cockpit.html and SSI_Solar_Reliability_Metrics.xlsx must all derive
from it, not carry their own hardcoded copies that can drift apart.
Run from repo root: PYTHONPATH=. python3 tests/test_pricing.py
"""
import json
import os

import yaml

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def test_74_pricing_yaml_corrected():
    with open(os.path.join(REPO_ROOT, "pricing.yaml")) as f:
        pricing = yaml.safe_load(f)
    saas = pricing["offerings"]["solar_saas"]["usd_per_mwdc_year"]
    scada = pricing["offerings"]["scada_monitoring"]["usd_per_mwdc_year"]
    assert saas == 120.0, f"solar_saas.usd_per_mwdc_year should be 120.0 (corrected), got {saas}"
    assert scada == 48.0, f"scada_monitoring.usd_per_mwdc_year should be 48.0 (corrected), got {scada}"
    print("test 74a (pricing.yaml corrected at source): passed - SaaS $120/MWdc/yr, SCADA $48/MWdc/yr")


def test_74_explorer_uses_corrected_rates():
    """Spot-check a site in explorer.html's payload whose only recommended
    offering is Solar SaaS or SCADA Monitoring - its annual_fee_usd must be
    consistent with the corrected per-MWdc rate, not the old one."""
    path = os.path.join(REPO_ROOT, "explorer.html")
    if not os.path.exists(path):
        print("test 74b (explorer uses corrected rates): skipped, explorer.html not built")
        return
    with open(path) as f:
        html = f.read()
    marker = '<script type="application/json" id="payload-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    checked = 0
    for s in payload["sites"]:
        offerings = s.get("recommended_offerings") or []
        mwdc = s.get("mwdc")
        fee = s.get("annual_fee_usd")
        if offerings == ["Solar SaaS"] and mwdc and fee:
            expected = 120.0 * mwdc
            assert abs(fee - expected) < max(1.0, 0.01 * expected), (
                f"{s['site']}: SaaS-only fee {fee} doesn't match corrected rate 120*{mwdc}={expected}")
            checked += 1
        elif offerings == ["SCADA Monitoring"] and mwdc and fee:
            expected = 48.0 * mwdc
            assert abs(fee - expected) < max(1.0, 0.01 * expected), (
                f"{s['site']}: SCADA-only fee {fee} doesn't match corrected rate 48*{mwdc}={expected}")
            checked += 1
        if checked >= 20:
            break
    assert checked > 0, "no single-offering sites found to spot-check - widen the search if this fires"
    print(f"test 74b (explorer uses corrected rates): passed - {checked} single-offering sites verified against pricing.yaml")


def test_74_cockpit_agrees_with_explorer_rates():
    """Same spot-check as test_74b, but against ceo_cockpit.html's payload -
    the two artefacts must derive fee potential from the same pricing.yaml
    rates, not drift apart (CEO_COCKPIT_REVISIONS_PASS2.md Part B3's build
    assertion)."""
    path = os.path.join(REPO_ROOT, "ceo_cockpit.html")
    if not os.path.exists(path):
        print("test 74c (cockpit agrees with explorer rates): skipped, ceo_cockpit.html not built")
        return
    with open(path) as f:
        html = f.read()
    marker = '<script type="application/json" id="payload-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    payload = json.loads(html[start:end])
    checked = 0
    for play in payload.get("plays", []):
        offering = play.get("offering")
        mwdc = play.get("mwdc")
        fee = play.get("annual_fee_usd")
        rate = {"Solar SaaS": 120.0, "SCADA Monitoring": 48.0}.get(offering)
        if rate is None or not mwdc or not fee:
            continue
        expected = rate * mwdc
        assert abs(fee - expected) < max(1.0, 0.01 * expected), (
            f"play {play.get('play_id')}: {offering} fee {fee} doesn't match "
            f"corrected rate {rate}*{mwdc}={expected} - cockpit and explorer disagree on price")
        checked += 1
    assert checked > 0, "no single-offering plays found to spot-check - widen the search if this fires"
    print(f"test 74c (cockpit agrees with explorer rates): passed - {checked} plays verified against pricing.yaml")


if __name__ == "__main__":
    test_74_pricing_yaml_corrected()
    test_74_explorer_uses_corrected_rates()
    test_74_cockpit_agrees_with_explorer_rates()
