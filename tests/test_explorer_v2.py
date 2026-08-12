"""Acceptance tests 34, 36, 37, 38 from EXPLORER_V2_IMPROVEMENTS.md Part I -
run after s11_explorer.py has written explorer.html. Tests 35, 39-49 are
not yet applicable: they check quadrant/pricing/RVM/owner rollups, none of
which are wired up yet (Parts E/F/D of the same brief). Run from repo
root: PYTHONPATH=. python3 tests/test_explorer_v2.py
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


def test_38_map_offline_and_markers_land_in_state():
    """explorer.html renders the US map with networking fully disabled,
    and every site marker's Albers-projected position falls inside its own
    state's polygon (point-in-polygon in the same planar space the map
    itself renders in, so this can't pass by coincidence)."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("test 38: skipped, playwright not installed")
        return
    import glob
    candidates = glob.glob("/opt/pw-browsers/chromium*/chrome-linux/chrome")
    if not candidates:
        print("test 38: skipped, no chromium binary found")
        return
    path = "file://" + os.path.join(REPO_ROOT, "explorer.html")
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=candidates[0], headless=True)
        context = browser.new_context()
        context.route("**/*", lambda route: route.abort() if not route.request.url.startswith("file://") else route.continue_())
        page = context.new_page()
        errors = []
        page.on("pageerror", lambda exc: errors.append(str(exc)))
        page.goto(path)
        page.wait_for_timeout(400)
        n_states = page.locator("path.geo").count()
        assert n_states == 51, f"expected 51 state polygons rendered offline, got {n_states}"
        assert not errors, f"page errors while rendering the offline map: {errors}"

        result = page.evaluate("""
        () => {
          function pointInPoly(pt, poly) {
            let inside = false;
            for (let i=0, j=poly.length-1; i<poly.length; j=i++) {
              const xi=poly[i][0], yi=poly[i][1], xj=poly[j][0], yj=poly[j][1];
              if (((yi>pt[1]) !== (yj>pt[1])) && (pt[0] < (xj-xi)*(pt[1]-yi)/(yj-yi)+xi)) inside = !inside;
            }
            return inside;
          }
          function testFeature(feat, pt) {
            const polys = feat.geometry.type === 'Polygon' ? [feat.geometry.coordinates] : feat.geometry.coordinates;
            return polys.some(rings => pointInPoly(pt, rings[0]));
          }
          let checked = 0, correct = 0, misses = [];
          for (const s of DATA.sites) {
            if (s.lat===null || s.lon===null || !s.state) continue;
            const feat = STATE_FEATURES.find(f => STATE_ABBR[f.properties.name] === s.state);
            if (!feat) continue;
            checked++;
            const p = ALBERS_PROJ([s.lon, s.lat]);
            if (p && testFeature(feat, p)) correct++;
            else misses.push(s.site);
          }
          return {checked, correct, misses};
        }
        """)
        browser.close()
    assert result["checked"] > 0, "no sites had lat/lon+state to check"
    assert result["correct"] == result["checked"], f"markers landed outside their state polygon: {result['misses']}"
    print(f"test 38 (map offline + markers-in-state): passed, {n_states} states, "
          f"{result['correct']}/{result['checked']} markers land in their own state")


if __name__ == "__main__":
    test_34_latest_scored()
    test_36_tier_consistency()
    test_37_slope_gating()
    test_38_map_offline_and_markers_land_in_state()
