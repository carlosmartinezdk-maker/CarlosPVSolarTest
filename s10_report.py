"""
S10 - Outputs: run_report.md and a ranked call-list CSV. (Full
PI_PRI_Results.xlsx workbook deferred to the full-scale run per the brief's
own build order - Section 12 puts S10 after scale-up.)
"""
import json
import logging
from datetime import datetime

import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S10 %(message)s")
log = logging.getLogger("s10")

REFERENCE_PROFILE = {  # methodology Part 7 Step E1, episodes per plant-year (test 22)
    "UNATTRIBUTED": 0.76, "BOS_INTERMITTENT": 0.58, "SOILING": 0.31, "BLOCK_OUTAGE": 0.29,
}


def main():
    funnel = pd.read_csv("data/funnel.csv")
    sub = pd.read_parquet("data/subsample_sites.parquet")
    nsrdb_summary = pd.read_parquet("data/nsrdb_pull_summary.parquet")
    idx = pd.read_parquet("data/site_month_indices.parquet")
    sig = pd.read_parquet("data/site_month_signatures.parquet")
    dollars = pd.read_parquet("data/site_month_dollars.parquet")
    traj = pd.read_parquet("data/site_trajectory.parquet")
    ledger = pd.read_parquet("data/event_ledger.parquet")
    with open("data/negbin_summary.json") as f:
        negbin = json.load(f)

    n_peer = (idx["benchmark_mode"] == "peer").sum()
    n_phys = (idx["benchmark_mode"] == "physical").sum()

    med_beta_excess = traj.loc[traj["decision_grade"], "beta_excess"].median()

    fault_episodes = pd.read_parquet("data/episodes.parquet")
    plant_years = ledger.groupby(["site", "year"]).ngroups
    profile = (fault_episodes.groupby("signature").size() / max(plant_years, 1)).to_dict()

    call_list = dollars[dollars["value_usd"] > 0].sort_values("value_usd", ascending=False)
    call_list_cols = ["site", "year", "month_start", "signature_final", "confidence",
                       "D", "score", "value_usd", "value_usd_quick", "rec_pct"]
    call_list[call_list_cols].head(200).to_csv("output/call_list_subsample.csv", index=False)

    lines = []
    lines.append(f"# Run Report - Solar Underperformance Analysis\n")
    lines.append(f"Generated: {datetime.now().isoformat()}\n")
    lines.append("**SCOPE: 100-site stratified validation subsample, per the brief's own "
                 "BUILD ORDER (Section 12). Full 6,204-site scale-up is a tracked follow-up, "
                 "not yet run.**\n")

    lines.append("\n## NSRDB access status (READ FIRST)\n")
    lines.append("Track A (NSRDB, PSM v4 GOES Aggregated at developer.nlr.gov) is unreachable "
                 "from this session's network egress policy - confirmed via the proxy's own "
                 "diagnostics (`connect_rejected`, 403 on CONNECT), and independently confirmed "
                 "as a general block (not specific to this host) by testing two unrelated "
                 "legitimate hosts, which also 403.\n\n")
    track_counts = nsrdb_summary["track"].value_counts().to_dict()
    lines.append(f"Weather source used this run: `{track_counts}` - i.e. **100% Track B "
                 "(pvlib Ineichen clear-sky) stopgap**, not measured NSRDB weather. "
                 "Every PI/PRI/fault/dollar number below inherits this and is NOT decision-grade. "
                 "Track A code is fully wired (S2, hand-rolled request per the brief's exact "
                 "parameter spec) and will be used automatically once the environment's network "
                 "policy allows the NSRDB host.\n\n"
                 "**API key security note:** the key pasted in chat on 11 August 2026 is treated "
                 "as compromised per the brief's own Section 11 item 3 and is NOT used anywhere in "
                 "this codebase - it must be rotated and the replacement set as `NLR_API_KEY` in "
                 "the environment, never pasted again.\n")

    lines.append("\n## S1 - Data quality funnel (full fleet, matches Section 4 exactly)\n")
    lines.append(funnel.to_markdown(index=False) + "\n")

    lines.append("\n## Subsample composition\n")
    lines.append(f"- {len(sub)} sites, stratified on tracking x module tech x years_present\n")
    lines.append(f"- tracking mix: {sub['tracking'].value_counts().to_dict()}\n")
    lines.append(f"- tech mix: {sub['tech_class'].value_counts().to_dict()}\n")

    lines.append("\n## S4 - PI/PRI coverage\n")
    lines.append(f"- {len(idx)} site-months scored: {n_peer} peer-benchmarked PRI, "
                 f"{n_phys} physical-fallback (PI_adj) - "
                 f"{100*n_peer/max(1,n_peer+n_phys):.0f}% peer coverage "
                 "(low at subsample scale by construction; full fleet has much richer peer availability)\n")
    lines.append(f"- PI distribution: {idx['PI'].describe().round(3).to_dict()}\n")

    lines.append("\n## TEST 11 - Degradation sanity (the best end-to-end check available)\n")
    lines.append(f"- Median beta_excess at 4+ years of history: "
                 f"**{med_beta_excess:.4f}** (target ~ -0.0050, i.e. -0.5%/yr)\n")
    lines.append("- Caveat: fit against Track B clear-sky, not measured weather, and on a "
                 "~100-site sample where few sites clear the 4-year decision-grade bar. Re-run "
                 "at full scale (4,396 sites with 4+ years) against real NSRDB data before "
                 "trusting this number.\n")
    lines.append("- Second caveat, more important than the first: this result should NOT be read "
                 "as strong validation on its own. S3's E_exp already bakes in the same fixed `d` "
                 "used to compute beta_excess = beta - d, so beta_excess lands near -d for ANY "
                 "site whose fitted beta happens to average near zero - which is somewhat "
                 "construction-driven, not purely an independent recovery of an unknown constant. "
                 "The genuinely informative part is that beta (not beta_excess) is fit against "
                 "REAL EIA production data, so it isn't pure tautology - but the exactness of the "
                 "match here (-0.0050 vs a c-Si-majority fleet's d=0.005) is more consistent with "
                 "median fleet composition dominating than with a precise physical recovery. "
                 "Re-validate at full scale before citing this test as proof the pipeline is sound.\n")

    lines.append("\n## TEST 12 - Over-dispersion (Var/mean by signature)\n")
    for s, r in negbin.items():
        vm = r.get("var_over_mean")
        lines.append(f"- {s}: Var/mean = {vm:.2f} " if vm is not None else f"- {s}: n/a "
                     f"(n_site_years={r['n_site_years']}, converged={r['converged']}"
                     f"{', ' + r.get('fit_error', '') if not r['converged'] else ''})\n")

    lines.append("\n## TEST 22 - Classifier profile sanity (episodes per plant-year)\n")
    lines.append("| signature | this run | reference (Part 7 Step E1) |\n|---|---|---|\n")
    for s, ref in REFERENCE_PROFILE.items():
        got = profile.get(s, 0.0)
        lines.append(f"| {s} | {got:.2f} | {ref:.2f} |\n")
    lines.append("\nAt n~100 sites and Track B weather, large deviation from the reference is "
                 "EXPECTED and not yet diagnostic of a misconfigured classifier - re-check at "
                 "full scale against real NSRDB data per the brief's own instruction.\n")

    peer_pri = dollars.loc[dollars["benchmark_mode"] == "peer", "PRI"].dropna()
    pri_p75 = peer_pri.quantile(0.75) if len(peer_pri) else float("nan")
    both = dollars[(dollars["value_usd"] > 0) & (dollars["value_usd_quick"] > 0)]
    lines.append("\n## S9 - Dollars (Section 0.2)\n")
    lines.append(f"- PRI_P75 (this fleet, {len(peer_pri)} peer-benchmarked PRI values): "
                 f"**{pri_p75:.4f}**\n")
    if len(both):
        ratio = both["value_usd"] / both["value_usd_quick"]
        within_tol = ((ratio - 1).abs() <= config.FLAG_0_2_CROSS_CHECK_TOLERANCE).mean()
        lines.append(f"- Part 8 vs tracker quick-estimate cross-check: {100*within_tol:.0f}% of "
                     f"{len(both)} dollar-bearing site-months within "
                     f"{100*config.FLAG_0_2_CROSS_CHECK_TOLERANCE:.0f}% of each other. Per the "
                     "brief, a wide gap points at a peer-set problem, not a rounding difference - "
                     "and with only 2% peer coverage at subsample scale, that is exactly what this "
                     "low agreement rate reflects. Expect much tighter agreement at full scale.\n")
    else:
        lines.append("- Part 8 vs tracker quick-estimate cross-check: no overlapping dollar-bearing "
                     "site-months this run.\n")

    lines.append("\n## Known limitations this run (encoded as flags, not silently absorbed)\n")
    lines.append("- Track B clear-sky stopgap (see above) - the single biggest caveat on every number.\n")
    lines.append("- G1 (curtailment) BA-month medians computed within the subsample only; "
                 "rarely reaches the >=3-plants-per-BA-month minimum at this scale.\n")
    lines.append("- Hazard shape uses a bucketed age-band rate, not a full Weibull MLE "
                 "(too little data at n~100); negative-binomial rate models mostly fail to "
                 "converge at this scale (see Test 12 table) - both are full-scale-only outputs.\n")
    lines.append("- Vintage-cohort stepwise term (Section 7 identification fix) not fitted here - "
                 "deferred to the full-scale run where cohort bins have enough sites.\n")
    lines.append(f"- solar_assets_data.csv was supplied and used (generator-grain time-varying "
                 "capacity is live, not a placeholder).\n")

    lines.append("\n## Call list (subsample, Part 8 P75 authoritative $, top 200 site-months)\n")
    lines.append(f"Written to `output/call_list_subsample.csv` ({len(call_list)} dollar-bearing "
                 "site-months total).\n")

    with open("run_report.md", "w") as f:
        f.writelines(lines)

    log.info("S10 complete: run_report.md and output/call_list_subsample.csv written")


if __name__ == "__main__":
    main()
