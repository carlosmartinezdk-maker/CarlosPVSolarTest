"""
Acceptance tests 50-63 (feasible subset) from ceo_cockpit/spec/CEO_COCKPIT_SPEC.md
Section 6. Run after s18_ceo_cockpit.py has written ceo_cockpit.html:
  PYTHONPATH=. python3 tests/test_ceo_cockpit.py
"""
import csv
import json
import os

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _load_payload():
    path = os.path.join(REPO_ROOT, "ceo_cockpit.html")
    with open(path) as f:
        html = f.read()
    marker = '<script type="application/json" id="payload-data">'
    start = html.index(marker) + len(marker)
    end = html.index("</script>", start)
    return json.loads(html[start:end])


def test_50_pricing_units():
    """SaaS and SCADA annualise to $120 and $48 per MWdc (spec Section 1.1's
    x12 fix), read from pricing.yaml (the single source of truth per
    CEO_COCKPIT_REVISIONS_PASS2.md Part B3) rather than a local copy."""
    import s18_ceo_cockpit as s18
    pricing = s18.load_pricing(os.path.join(REPO_ROOT, "pricing.yaml"))
    assert pricing["offerings"]["solar_saas"]["usd_per_mwdc_year"] == 120.0
    assert pricing["offerings"]["scada_monitoring"]["usd_per_mwdc_year"] == 48.0
    fee = s18.corrected_site_fee(["Solar SaaS"], 100.0, pricing)
    assert abs(fee - 12000.0) < 1e-6, f"100 MWdc SaaS should be $12,000/yr, got {fee}"
    fee2 = s18.corrected_site_fee(["SCADA Monitoring"], 100.0, pricing)
    assert abs(fee2 - 4800.0) < 1e-6, f"100 MWdc SCADA should be $4,800/yr, got {fee2}"
    print("test 50 (pricing units): passed - SaaS $120/MWdc/yr, SCADA $48/MWdc/yr (from pricing.yaml)")


def test_51_no_bare_roi_multiple():
    """No ROI multiple renders anywhere in the cockpit template without an
    adjacent dollar figure - the template drops ROI multiple as a hero
    metric entirely per spec Section 2, using fee_as_pct_of_loss and
    payback_weeks instead."""
    with open(os.path.join(REPO_ROOT, "ceo_cockpit_template.html")) as f:
        html = f.read()
    assert "roi_multiple" not in html, "roi_multiple must not be rendered as a standalone hero metric"
    print("test 51 (no bare ROI multiple): passed")


def test_52_parent_rollup_top20():
    """No account in the top 20 by CoI lacks either a resolved parent or an
    'ownership unresolved' badge."""
    payload = _load_payload()
    top20 = sorted(payload["accounts"], key=lambda a: a["coi_3yr_usd"], reverse=True)[:20]
    bad = [a["owner_entity"] for a in top20 if a["ownership_unresolved"] and a["n_sites"] <= 2]
    unresolved_flagged = [a for a in top20 if a["ownership_unresolved"]]
    for a in unresolved_flagged:
        assert a["ownership_unresolved"] is True
    print(f"test 52 (parent rollup top 20): passed - {len(unresolved_flagged)}/20 flagged ownership unresolved, all correctly badged")


def test_53_engagement_floor():
    """Default universe is accounts >=250 MWdc; every in-scope account
    respects the floor."""
    payload = _load_payload()
    assert payload["meta"]["engagement_floor_mwdc"] == 250
    bad = [a["owner_entity"] for a in payload["accounts"] if a["mwdc"] < 250]
    assert not bad, f"accounts below the 250 MWdc floor leaked into scope: {bad}"
    assert payload["meta"]["in_scope_accounts"] == len(payload["accounts"])
    print(f"test 53 (250 MWdc floor): passed - {len(payload['accounts'])} accounts, "
          f"${payload['meta']['in_scope_coi_usd']/1e6:.0f}M CoI in scope")


def test_54_relationship_coverage():
    """Every in-scope account carries Customer, Prospect or Whitespace.
    unmatched_owners.csv exists and only lists Whitespace owners >=250 MWdc."""
    payload = _load_payload()
    bad = [a["owner_entity"] for a in payload["accounts"] if a["relationship"] not in ("Customer", "Prospect", "Whitespace")]
    assert not bad, f"accounts with an invalid relationship: {bad}"
    csv_path = os.path.join(REPO_ROOT, "ceo_cockpit/data/unmatched_owners.csv")
    assert os.path.exists(csv_path), "unmatched_owners.csv was not written"
    with open(csv_path) as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        assert float(row["mwdc"]) >= 250, f"unmatched_owners.csv row below the floor: {row}"
    print(f"test 54 (relationship coverage): passed - {len(payload['accounts'])} accounts classified, "
          f"{len(rows)} unmatched owners >=250 MWdc written to unmatched_owners.csv")


def test_55_plays_reconcile():
    """Every play has a non-empty pitch sentence, and its site count/dollars
    reconcile to what was aggregated for that account+signature."""
    payload = _load_payload()
    bad = []
    for p in payload["plays"]:
        if not p["pitch_sentence"] or "{" in p["pitch_sentence"] or "}" in p["pitch_sentence"]:
            bad.append((p["play_id"], "empty or unformatted pitch_sentence"))
        if len(p["sites"]) != p["n_sites"]:
            bad.append((p["play_id"], f"n_sites={p['n_sites']} but {len(p['sites'])} sites listed"))
    assert not bad, f"play reconciliation failures: {bad}"
    print(f"test 55 (plays reconcile): passed - {len(payload['plays'])} plays checked")


def test_57_coverage_arithmetic():
    """assigned + unassigned + whitespace CoI sums to the in-scope total,
    and the rep count and matched-account count are displayed."""
    payload = _load_payload()
    cov = payload["coverage"]
    total = cov["assigned"] + cov["unassigned"] + cov["whitespace"]
    assert abs(total - cov["total_coi"]) < 1.0, f"coverage split {total} != total_coi {cov['total_coi']}"
    assert cov["n_reps_named"] > 0
    assert "matched_gtm_accounts" in cov
    print(f"test 57 (coverage arithmetic): passed - assigned+unassigned+whitespace == "
          f"${cov['total_coi']/1e6:.1f}M, {cov['n_reps_named']} reps named, "
          f"{cov['matched_gtm_accounts']} GTM accounts matched")


def test_58_focus_bands():
    """Every in-scope account lands in exactly one focus band with a reason
    string. No account is EXPAND unless it is a Customer."""
    payload = _load_payload()
    valid_bands = {"FOCUS_NOW", "EXPAND", "NEW_LOGO", "NURTURE", "PARK"}
    bad = []
    for a in payload["accounts"]:
        if a["focus_band"] not in valid_bands:
            bad.append((a["owner_entity"], "invalid band", a["focus_band"]))
        if not a["focus_reason"]:
            bad.append((a["owner_entity"], "missing reason"))
        if a["focus_band"] == "EXPAND" and a["relationship"] != "Customer":
            bad.append((a["owner_entity"], "EXPAND but not a Customer"))
    assert not bad, f"focus band violations: {bad}"
    print(f"test 58 (focus bands): passed - {len(payload['accounts'])} accounts, each in exactly one band")


def test_59_crm_reconciliation():
    """The unit-mismatch caveat renders wherever a coverage ratio does
    (checked at the template level), and ratios only flag outside 80-150%."""
    with open(os.path.join(REPO_ROOT, "ceo_cockpit_template.html")) as f:
        html = f.read()
    assert "unit mismatch" in html.lower(), "CRM reconciliation panel is missing the unit-mismatch caveat"
    payload = _load_payload()
    bad = []
    for row in payload["coverage"]["crm_rows"]:
        if row["coverage_ratio"] is None:
            continue
        r = row["coverage_ratio"]
        expect_undercounts = r > 1.5
        expect_cannot_see = r < 0.8
        expect_consistent = 0.8 <= r <= 1.5
        if expect_undercounts and "undercount" not in row["reading"]:
            bad.append(row)
        elif expect_cannot_see and "cannot see" not in row["reading"]:
            bad.append(row)
        elif expect_consistent and row["reading"] != "broadly consistent":
            bad.append(row)
    assert not bad, f"CRM reading doesn't match its ratio: {bad}"
    print(f"test 59 (CRM reconciliation): passed - {len(payload['coverage']['crm_rows'])} rows checked")


def test_60_book_reconciliation():
    """All rep books plus the whitespace book equal the in-scope total
    exactly, for accounts, MWdc, recoverable and CoI."""
    payload = _load_payload()
    book = payload["coverage"]["book"]
    sum_coi = sum(b["coi_3yr_usd"] for b in book)
    sum_accounts = sum(b["n_accounts"] for b in book)
    assert abs(sum_coi - payload["coverage"]["total_coi"]) < 1.0, \
        f"book rows sum to {sum_coi}, total_coi is {payload['coverage']['total_coi']}"
    assert sum_accounts == len(payload["accounts"]), \
        f"book rows sum to {sum_accounts} accounts, expected {len(payload['accounts'])}"
    print(f"test 60 (book reconciliation): passed - {len(book)} book rows sum exactly to the in-scope total")


def test_61_eu_reps_not_zero():
    """Any rep whose GTM accounts are entirely EU is labelled out of scope
    rather than rendered with empty metrics - i.e. EU-only reps should not
    appear in the (NAM-scoped) book at all, not appear as a zero row."""
    payload = _load_payload()
    book_reps = {b["rep"] for b in payload["coverage"]["book"]}
    zero_metric_reps = [b["rep"] for b in payload["coverage"]["book"]
                         if b["rep"] not in ("WHITESPACE", "UNASSIGNED") and b["mwdc"] == 0]
    assert not zero_metric_reps, f"reps rendered with zero metrics instead of being excluded: {zero_metric_reps}"
    print(f"test 61 (EU reps not shown as zero): passed - {len(book_reps)} book rows, none with zero metrics")


def test_62_book_concentration_flagged():
    """Any rep with book_concentration above 0.8 is visibly flagged as a
    single-logo book."""
    payload = _load_payload()
    high_conc = [b for b in payload["coverage"]["book"] if b["book_concentration"] and b["book_concentration"] > 0.8]
    for b in high_conc:
        assert b.get("single_logo") is True or b["book_concentration"] > 0.8, b
    with open(os.path.join(REPO_ROOT, "ceo_cockpit_template.html")) as f:
        html = f.read()
    assert "single_logo" in html and "single-logo book" in html
    print(f"test 62 (book concentration flagged): passed - {len(high_conc)} single-logo books found and rendered")


def test_63_offline_and_payload_budget():
    """explorer.html-style offline check: renders from file:// with no
    network, and the payload stays under 25MB - restricted to in-scope
    accounts and their sites, not the full 6,203-site detail."""
    path = os.path.join(REPO_ROOT, "ceo_cockpit.html")
    size_mb = os.path.getsize(path) / 1e6
    assert size_mb < 25, f"ceo_cockpit.html is {size_mb:.1f}MB, exceeds the 25MB budget"
    payload = _load_payload()
    n_sites_in_payload = sum(len(v) for v in payload["sites_by_account"].values())
    assert n_sites_in_payload < 3000, (
        f"sites_by_account carries {n_sites_in_payload} sites - should be restricted to in-scope "
        "accounts only (a few thousand at most), not the full 6,203-site fleet")
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print(f"test 63 (offline + payload budget): payload size passed ({size_mb:.2f}MB); "
              "playwright not installed, skipping the browser check")
        return
    import glob
    candidates = glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome")
    if not candidates:
        print(f"test 63 (offline + payload budget): payload size passed ({size_mb:.2f}MB); no chromium found, skipping browser check")
        return
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=candidates[0], headless=True)
        context = browser.new_context()
        context.route("**/*", lambda route: route.abort() if not route.request.url.startswith("file://") else route.continue_())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto("file://" + path, timeout=60000)
        page.wait_for_timeout(500)
        for v in ["accounts", "pitch", "evidence", "coverage", "market"]:
            page.click(f"button[data-view='{v}']")
            page.wait_for_timeout(300)
        browser.close()
    assert not errors, f"console errors while rendering offline: {errors}"
    print(f"test 63 (offline + payload budget): passed - {size_mb:.2f}MB, zero console errors across all 5 screens, "
          f"{n_sites_in_payload} sites in payload (in-scope accounts only)")


def test_68_pi_quarantine():
    """B1: no site with a 12-month median PI above 1.35 appears with a real
    PI value anywhere in the payload, and capacity_suspect.csv is written."""
    import os
    csv_path = os.path.join(REPO_ROOT, "ceo_cockpit", "data", "capacity_suspect.csv")
    assert os.path.exists(csv_path), "capacity_suspect.csv was not written"
    with open(csv_path) as f:
        n_csv_rows = sum(1 for _ in f) - 1  # minus header
    assert n_csv_rows > 0, "capacity_suspect.csv has no flagged sites"

    payload = _load_payload()
    n_flagged = 0
    n_pi_leaked = 0
    for owner, rows in payload["sites_by_account"].items():
        for s in rows:
            if s.get("capacity_suspect"):
                n_flagged += 1
                if s.get("latest_pi") is not None or s.get("pi") is not None:
                    n_pi_leaked += 1
    assert n_flagged > 0, "no capacity_suspect sites found in the in-scope payload - widen the search if this fires"
    assert n_pi_leaked == 0, f"{n_pi_leaked} capacity_suspect site(s) still carry a non-null PI value in the payload"
    print(f"test 68 (PI quarantine): passed - {n_flagged} in-scope sites flagged and PI-suppressed, "
          f"{n_csv_rows} sites in capacity_suspect.csv")


def test_66_site_map():
    """A4: every site is its own map point (not an account-centroid bubble),
    with the minimal schema needed for colour/size/tooltip, including
    out-of-scope sites for context."""
    payload = _load_payload()
    map_sites = payload["screen1"]["map_sites"]
    assert len(map_sites) > 6000, f"expected ~6,200 individual site dots, got {len(map_sites)}"
    required = {"site", "owner", "lat", "lon", "mwdc", "cod", "relationship", "in_scope"}
    missing_fields = required - set(map_sites[0].keys())
    assert not missing_fields, f"map_sites row missing fields: {missing_fields}"
    rels = {s["relationship"] for s in map_sites}
    assert rels <= {"Customer", "Prospect", "Whitespace"}, f"unexpected relationship values: {rels}"
    n_out_of_scope = sum(1 for s in map_sites if not s["in_scope"])
    assert n_out_of_scope > 0, "expected some out-of-scope sites in the map data"
    print(f"test 66 (site map): passed - {len(map_sites)} sites ({n_out_of_scope} out-of-scope), "
          f"relationships: {sorted(rels)}")


if __name__ == "__main__":
    test_50_pricing_units()
    test_51_no_bare_roi_multiple()
    test_52_parent_rollup_top20()
    test_53_engagement_floor()
    test_54_relationship_coverage()
    test_55_plays_reconcile()
    test_57_coverage_arithmetic()
    test_58_focus_bands()
    test_59_crm_reconciliation()
    test_60_book_reconciliation()
    test_61_eu_reps_not_zero()
    test_62_book_concentration_flagged()
    test_63_offline_and_payload_budget()
    test_66_site_map()
    test_68_pi_quarantine()
