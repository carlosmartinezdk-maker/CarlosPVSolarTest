"""Assemble a self-contained results infographic: python build.py gas|bess  (run build_data.py first)."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
D3 = Path(sys.argv[2]) if len(sys.argv) > 2 else None

COMMON_FOOT = [
    "<b>Sources.</b> EIA-923 Schedules 2–5 monthly (final revisions 2019–2024; 2025 Final release, published after the 30 Jun 2026 early "
    "release the analysis spec anticipated). 2025 is the first final vintage and may still be revised. EIA-860 annual vintages 2019–2025 "
    "(generator, plant and ownership schedules).",
    "<b>Ownership.</b> Customer = parent-company group from the fleet production workbook's customer mapping "
    "(plant-level where the plant appears there; otherwise the EIA-860 Schedule 4 owner or operating utility through the workbook's "
    "owner-to-customer table). Owners the mapping does not cover, mostly single-asset LLCs and small engine plants, appear under "
    "their own names. <b>SSI status</b> comes from the current SSI customer list: 43 of its 173 names appear as US customer groups, and the "
    "rest (mainly European, Australian and other non-US entities) have no US sites in this data.",
    "<b>Capacity by year</b> is each year's EIA-860 nameplate (time-varying, including retirements and augmentation). It is not "
    "reconstructed from commissioning dates, so uprates are dated when EIA-860 reports them rather than backdated. Sites with no "
    "scoreable month are not shown, and sites outside the Albers USA projection are dropped from the map and data. __COVERAGE__",
]
GAS_FOOT = [
    "<b>Heat rate</b> is corrected for load factor and ambient temperature against a fleet reference envelope (per-class p10, "
    "isotonic in load factor). It is not a design guarantee. HRI = reference ÷ corrected heat rate (higher is better; 1.00 = the fleet's "
    "best-decile envelope). PRI compares each plant with matched healthy peers. Below-floor months (CHP fuel allocation, CA generation "
    "missing) are quarantined.",
    "<b>Fuel cost</b> is the plant's own delivered gas price where reported (53.8% of plant-months in the Page 5 file), otherwise a state "
    "or national average. Check the fuel-cost tier in each row's detail line; national-tier leads are low-conviction.",
    "<b>Recovery fractions and remediation costs are unvalidated placeholders</b> pending vendor quotes. Dollar figures are indicative, "
    "not quotes. Recoverable $ is capped at each unit's own best heat rate. EIA-923 annual respondents (most small GTs and engines) carry "
    "EIA-allocated monthly values, so their monthly components are unresolved. Gas Steam capacity matching is ~52–55%: indicative only.",
]
BOP_FOOT = [
    "<b>The balance-of-plant index is a propensity score, not a diagnosis.</b> It detects a system-level thermodynamic consequence "
    "(a summer heat-rate penalty that survives ambient correction, consistent with condenser or cooling-water degradation), never a "
    "component fault. The measured detection floor is a 4.5% heat-rate change in a single month and 1.30% sustained over twelve "
    "(month-over-month noise σ = 2.25% on stable baseload combined cycle; this dataset measures 2.63%). Total failure of the largest "
    "auxiliary pump on a 500 MW plant is about 1.2% of output, so individual pumps sit below the floor by construction. Confirming a "
    "cause requires an on-site condenser performance test and a pump vibration survey.",
    "<b>Confidence.</b> CEMS-backed rows use EPA CAMPD hourly gross load (2024–2025) for starts, trips and ramping, validated against "
    "EIA-923 heat input (median ratio 1.00). Rows marked <i>low</i> confidence have no CEMS data; their cycling exposure is a weak "
    "monthly proxy (load-factor variability), trip and ramp components are missing, and the remaining weights are renormalised. "
    "Where monthly evidence is missing (annual respondents), the evidence components are set to the peer median.",
    "<b>BPRI</b> = 0.30·cooling signal + 0.25·unattributed/BoP deficit share + 0.15·starts + 0.10·trips + 0.05·ramping + "
    "0.10·BoP age (years since <i>original</i> COD) + 0.05·interruptible gas, each a 0–100 percentile within class × unit-size band "
    "× climate region. The weights are judgement, not measurement. <b>Confirmed</b>: cooling and deficit evidence both ≥ p75 and "
    "persistent ≥ 2 years. <b>Likely</b>: either ≥ p75 with exposure ≥ p60. <b>Exposed</b>: exposure ≥ p80 with no current "
    "evidence (the preventative sale). Recoverable $ counts only cooling and BoP-intermittent months in the last 24 months, "
    "annualised, with placeholder recovery fractions (0.75 / 0.60). It is not a quote.",
]
BESS_FOOT = [
    "<b>Efficiency is decomposed</b> by regressing charge/discharge on hours/discharge for each site: 1/intercept = conversion "
    "efficiency η_true, slope = continuous parasitic load P_aux. Apparent RTE (grid boundary) and η_true (conversion boundary) are both "
    "correct, at different measurement boundaries. Map colour is η_true relative to the median of its duration band, because C-rate "
    "moves efficiency.",
    "<b>Hybrids are quarantined</b> (PV at the same plant, RTE above 1, DC-coupled or co-located firming) because co-located charging is "
    "inconsistently metered. They appear grey and are excluded from the efficiency statistics and the efficiency chart. Degradation "
    "(fade, η trend) is not reported below 24 months of history. EIA-923 annual-respondent months (most of 2019–2022) are not scored "
    "monthly.",
    "<b>No dollar figure is shown because lost battery MWh have no PPA price.</b> The value of a cycle depends on the spread it "
    "captured, which requires nodal price data not in this dataset. Under-dispatch is commercial, not a technical fault. The warranty "
    "position assumes 6,000 cycles.",
]

CONFIGS = {
    "gas": {
        "title": "Gas Heat-Rate Results",
        "eyebrow": "US gas fleet · heat rate, degradation &amp; reliability · EIA-923 / EIA-860 2019–2025",
        "h1": "Where the US gas fleet burns fuel it does not need to",
        "sub": "Every gas plant and technology block, scored monthly on load- and temperature-corrected heat rate against a fleet "
               "envelope, matched peers and its own best months. Excess fuel is priced at the plant's own delivered gas cost and split "
               "into recoverable causes (fouling, hot-gas-path) and non-recoverable or by-design ones.",
        "techLabel": "Technology",
        "techColors": ["#8c5d3f", "#b5733f", "#a9906b", "#9c8a73"],
        "valueUnit": "usd", "valueName": "Recoverable $", "tableValueKey": "r",
        "chartTitle": "Excess fuel cost vs attainable target, stacked by signature",
        "chartNote": "Recoverable causes sit at the bottom (green/blue); non-recoverable (browns) and unresolved or by-design (greys) stack on top.",
        "indexName": "HRI (vs fleet p10 envelope)", "indexShort": "HRI", "naLabel": "No scoreable months",
        "sigLabels": ["Compressor fouling", "Hot-gas-path deterioration", "Cooling / condenser degradation", "BoP intermittent",
                      "Non-recoverable", "Cycling damage", "Unattributed",
                      "Annual reporter (unresolved)", "Duct firing (by design)", "Fuel-quality artefact", "Healthy (design gap to target)"],
        "sigColors": ["#6a9c78", "#4a8ca8", "#2f6680", "#8fb89c", "#8c5d3f", "#a9906b", "#9d9893", "#cdc8c2", "#b9b5b1", "#e0dcd7", "#ebe8e4"],
        "sigHatch": [0, 0, 0, 1, 0, 0, 0, 1, 0, 1, 0],
        "sigGroup": ["Recoverable", "Recoverable", "Recoverable", "Recoverable", "Non-recoverable", "Non-recoverable", "Unresolved / by design",
                     "Unresolved / by design", "Unresolved / by design", "Unresolved / by design", "Unresolved / by design"],
        "stackOrder": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10], "recoverableSigs": [0, 1, 2, 3],
        "confOptions": [["all", "All"], ["plant", "Plant-tier fuel cost only"]],
        "ssiSupplied": True, "footer": COMMON_FOOT + GAS_FOOT, "footerBop": BOP_FOOT + COMMON_FOOT,
        "tierColors": ["#b0452f", "#c47f45", "#c8b05a", "#b9b5b1"],
        "tierLabels": ["Confirmed", "Likely", "Exposed", "Low"],
    },
    "bess": {
        "title": "BESS Efficiency Results",
        "eyebrow": "US grid-scale batteries · efficiency, availability &amp; reliability · EIA-923 / EIA-860 2019–2025",
        "h1": "How much of a battery's round-trip loss is the cells, and how much is the air-conditioning",
        "sub": "Every US grid-scale battery, scored monthly. Apparent round-trip efficiency is split into true conversion efficiency and "
               "continuous parasitic load, availability is benchmarked against same-market peers, and throughput at stake is attributed "
               "to technical and commercial causes. Everything is in MWh and efficiency points; there are no dollars.",
        "techLabel": "Duration band",
        "techColors": ["#a3c4ac", "#6a9c78", "#4f7f5d", "#35573f"],
        "valueUnit": "mwh", "valueName": "MWh at stake", "tableValueKey": "v",
        "chartTitle": "Throughput at stake, stacked by signature",
        "chartNote": "Technical causes sit at the bottom (green/blue, hatched where colours are close); low-recovery state signatures (browns) and commercial / scheduled / data (greys) on top.",
        "indexName": "η_true ÷ duration-band median (standalone)", "indexShort": "η index", "naLabel": "Insufficient history / hybrid (quarantined)",
        "sigLabels": ["Full outage", "Partial availability", "Thermal / auxiliary", "Unattributed", "Cell degradation", "Capacity fade",
                      "Under-dispatch (commercial)", "Augmentation (scheduled)", "Hybrid artefact", "Healthy"],
        "sigColors": ["#4a8ca8", "#6a9c78", "#5f8fa6", "#7aa88c", "#8c5d3f", "#a9906b", "#b9b5b1", "#d3cfca", "#9d9893", "#ebe8e4"],
        "sigHatch": [0, 0, 1, 1, 0, 0, 0, 0, 1, 0],
        "sigGroup": ["Technical, recoverable", "Technical, recoverable", "Technical, recoverable", "Technical, recoverable",
                     "State (low recovery)", "State (low recovery)", "Commercial / scheduled / data", "Commercial / scheduled / data",
                     "Commercial / scheduled / data", "Commercial / scheduled / data"],
        "stackOrder": [0, 1, 2, 3, 4, 5, 6, 7, 8, 9], "recoverableSigs": [0, 1, 2, 3],
        "confOptions": [["all", "All"], ["h24", "≥24 months history"]],
        "ssiSupplied": True, "footer": COMMON_FOOT + BESS_FOOT,
    },
}
OUTFILE = {"gas": REPO / "gas_analysis" / "outputs" / "gas_results_infographic.html",
           "bess": REPO / "bess_analysis" / "outputs" / "bess_results_infographic.html"}


def drop_unprojectable(data, d3path):
    js = ("const vm=require('vm');const fs=require('fs');const ctx={};vm.createContext(ctx);"
          f"vm.runInContext(fs.readFileSync({json.dumps(str(d3path))},'utf8'),ctx);"
          "const pts=JSON.parse(fs.readFileSync(0,'utf8'));const p=ctx.d3.geoAlbersUsa();"
          "console.log(JSON.stringify(pts.map(q=>q[0]==null||q[1]==null||p([q[0],q[1]])===null)));")
    pts = [[s["lo"], s["la"]] for s in data["sites"]]
    out = subprocess.run(["node", "-e", js], input=json.dumps(pts), capture_output=True, text=True, check=True)
    bad = json.loads(out.stdout)
    dropped = [s["n"] for s, b in zip(data["sites"], bad) if b]
    data["sites"] = [s for s, b in zip(data["sites"], bad) if not b]
    return dropped


def main(kind, d3path):
    data = json.loads((HERE / "build" / f"{kind}_data.json").read_text())
    dropped = drop_unprojectable(data, d3path)
    cfg = json.loads(json.dumps(CONFIGS[kind]))
    yi = data["years"].index(2025)
    full = sum(v[yi] for v in data["fleetCap"].values())
    shown = sum((s["y"].get("2025") or {}).get("mw", 0) for s in data["sites"])
    cov = (f"Sites shown carry {shown / 1e3:,.1f} GW of the {full / 1e3:,.1f} GW EIA-860 fleet nameplate for 2025 "
           f"({shown / full * 100:.0f}%).")
    for k in ("footer", "footerBop"):
        if k in cfg:
            cfg[k] = [p.replace("__COVERAGE__", cov) for p in cfg[k]]
    t = (HERE / "template.html").read_text()
    topo = (HERE / "states-10m.min.json").read_text()
    cols = (HERE / f"site_columns_{kind}.js").read_text()
    html = (t.replace("/*__TOPO__*/", topo).replace("/*__DATA__*/", json.dumps(data, separators=(",", ":")))
             .replace("/*__CONFIG__*/", json.dumps(cfg, ensure_ascii=False)).replace("__SITE_COLUMNS__", cols)
             .replace("__TITLE__", cfg["title"]).replace("__EYEBROW__", cfg["eyebrow"]).replace("__H1__", cfg["h1"])
             .replace("__SUB__", cfg["sub"]))
    OUTFILE[kind].write_text(html)
    print(kind, "->", OUTFILE[kind], f"{OUTFILE[kind].stat().st_size / 1e6:.2f} MB;", len(data["sites"]), "sites;",
          "dropped (outside Albers USA):", dropped)


if __name__ == "__main__":
    main(sys.argv[1], D3 or Path("/tmp/claude-0/-home-user-CarlosPVSolarTest/5c49453f-37f7-57ac-9ed8-5fcab4df3410/scratchpad/d3.min.js"))
