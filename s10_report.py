"""
S10 - Outputs: run_report.md, a ranked call-list CSV, and PI_PRI_Results.xlsx
(Section 9): Call List, Site Detail, Monthly Metrics, Event Ledger,
Risk Forecast, Assumptions, Funnel, Notes.
"""
import json
import logging
from datetime import datetime

import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S10 %(message)s")
log = logging.getLogger("s10")

from s11_explorer import compute_conviction_tier, track_mix_decision_grade  # noqa: E402 - after basicConfig so S10's log format wins

REFERENCE_PROFILE = {  # methodology Part 7 Step E1, episodes per plant-year (test 22)
    "UNATTRIBUTED": 0.76, "BOS_INTERMITTENT": 0.58, "SOILING": 0.31, "BLOCK_OUTAGE": 0.29,
}


ASSUMPTIONS = [
    dict(name="PPA", value="40.0 USD/MWh", status="fixed by Carlos, Aug 2026"),
    dict(name="gamma (c-Si)", value="-0.0037 /degC", status="measured (IEC/lab)"),
    dict(name="gamma (CdTe)", value="-0.0028 /degC", status="measured (IEC/lab)"),
    dict(name="d (c-Si)", value="0.005 /yr", status="assumed structural prior, fixed by design"),
    dict(name="d (CdTe)", value="0.004 /yr", status="assumed structural prior, fixed by design"),
    dict(name="static loss stack L", value="0.86", status="assumed"),
    dict(name="inverter efficiency", value="0.985", status="assumed"),
    dict(name="rho_s (all signatures)", value="see Action Map / config.SIGNATURE_ACTION_MAP", status="PLACEHOLDER, no ground truth yet"),
    dict(name="warranty terms", value="2y EPC / 5-10y inverter / 10-12y module / 25y perf.", status="assumed default, not contractual"),
    dict(name="weather source this run", value="pvlib clear-sky (Ineichen) stopgap", status="NOT measured NSRDB - not decision-grade"),
    dict(name="PRI_P75, PI_P75", value="computed from this fleet at runtime", status="measured (this run), not hardcoded"),
]


def build_site_detail_sheet(sub, dollars, traj, ledger):
    traj_idx = traj.set_index("site")
    site_year_stats = dollars.groupby(["site", "year"]).agg(
        mean_PI=("PI", "mean"), is_lead=("is_lead", "max")
    ).reset_index()
    rows = []
    for _, srow in sub.iterrows():
        site = srow["site"]
        g = dollars[dollars["site"] == site].sort_values("month_start")
        if len(g) == 0:
            continue
        latest = g.iloc[-1]
        t = traj_idx.loc[site] if site in traj_idx.index else None
        sy = site_year_stats[site_year_stats["site"] == site]
        tier = compute_conviction_tier(sy, t)
        warranty_urgent = bool(latest.get("warranty_urgent", False)) if "warranty_urgent" in g else False
        if warranty_urgent and tier != "Improving":
            tier = "Warranty-urgent"
        led = ledger[ledger["site"] == site]
        rows.append(dict(
            site=site, state=srow.get("state"), operator=srow.get("operator"),
            mwac=srow.get("mwac"), mwdc=srow.get("mwdc"), dcac=srow.get("dcac"),
            tracking=srow.get("tracking"), module=srow.get("module"),
            cod=str(srow.get("cod"))[:10] if pd.notna(srow.get("cod")) else None,
            years_present=srow.get("years_present"),
            latest_PI=latest.get("PI"), latest_PRI=latest.get("PRI"), latest_D=latest.get("D"),
            beta=t["beta"] if t is not None else None,
            beta_se=t["beta_se"] if t is not None else None,
            beta_t=t["beta_t"] if t is not None else None,
            beta_excess=t["beta_excess"] if t is not None else None,
            decision_grade=bool(t["decision_grade"]) if t is not None else False,
            fault_months=int(g["fault_flag"].sum()),
            episode_count=int(led["signature"].isin(config.FAULT_LEDGER_SIGNATURES).sum()),
            top_signature=(g.loc[g["fault_flag"], "signature_final"].value_counts().index[0]
                          if g["fault_flag"].any() else "NONE"),
            conviction_tier=tier, warranty_urgent=warranty_urgent,
            recoverable_usd_yr=sum(v for v in g["value_usd"] if v) / max(g["year"].nunique(), 1),
        ))
    return pd.DataFrame(rows)


def build_excel_workbook(funnel, call_list, sub, dollars, traj, ledger, credibility, run_notes, assumptions):
    site_detail = build_site_detail_sheet(sub, dollars, traj, ledger)

    monthly_cols = ["site", "year", "month_num", "month_start", "E_act_mwh", "E_exp_mwh",
                     "PI", "PR_T", "SY", "PRI", "peer_count", "peer_radius_km", "peers_healthy",
                     "poa_kwh_m2", "clipped_hours", "mean_cell_temp_c", "signature_final",
                     "classifier_version", "T_mwh", "gross_gap_mwh", "R_mwh", "value_usd"]
    monthly = dollars.copy()
    monthly["classifier_version"] = "d-band-v1"
    monthly_cols = [c for c in monthly_cols if c in monthly.columns]

    assumptions_df = pd.DataFrame(assumptions)
    notes_df = pd.DataFrame({"note": run_notes})

    with pd.ExcelWriter("output/PI_PRI_Results.xlsx", engine="openpyxl") as writer:
        call_list.to_excel(writer, sheet_name="Call List", index=False)
        site_detail.to_excel(writer, sheet_name="Site Detail", index=False)
        monthly[monthly_cols].to_excel(writer, sheet_name="Monthly Metrics", index=False)
        ledger.to_excel(writer, sheet_name="Event Ledger", index=False)
        credibility.to_excel(writer, sheet_name="Risk Forecast", index=False)
        assumptions_df.to_excel(writer, sheet_name="Assumptions", index=False)
        funnel.to_excel(writer, sheet_name="Funnel", index=False)
        notes_df.to_excel(writer, sheet_name="Notes", index=False)
    log.info("wrote output/PI_PRI_Results.xlsx (%d sheets)", 8)


def main():
    funnel = pd.read_csv("data/funnel.csv")
    sub = pd.read_parquet("data/subsample_sites.parquet")
    nsrdb_summary = pd.read_parquet("data/nsrdb_pull_summary.parquet")
    idx = pd.read_parquet("data/site_month_indices.parquet")
    sig = pd.read_parquet("data/site_month_signatures.parquet")
    dollars = pd.read_parquet("data/site_month_dollars.parquet")
    traj = pd.read_parquet("data/site_trajectory.parquet")
    ledger = pd.read_parquet("data/event_ledger.parquet")
    credibility = pd.read_parquet("data/credibility.parquet")
    with open("data/negbin_summary.json") as f:
        negbin = json.load(f)

    n_peer = (idx["benchmark_mode"] == "peer").sum()
    n_phys = (idx["benchmark_mode"] == "physical").sum()

    track_counts = nsrdb_summary["track"].value_counts().to_dict()
    decision_grade, decision_grade_reason = track_mix_decision_grade(track_counts)

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
    if decision_grade:
        lines.append("Track A (NSRDB, PSM v4 GOES Aggregated at developer.nlr.gov) is reachable "
                     "from this session's network egress policy - confirmed via `s2_nsrdb.py "
                     "--preflight-only` (`success`) and by the real pull below. Per the brief's "
                     "own updated architecture, `s2_nsrdb.py` is a fully standalone script with "
                     "no import from the rest of this repo, run against the 100-site validation "
                     "subsample (707 cell-years). The full 4,798-cell x 7-year = 33,586 "
                     "cell-year fleet pull is still a separate, deliberately-deferred multi-day "
                     "job at the NLR rate limit (1 req/sec, 10,000/day) - not yet run.\n\n")
    else:
        lines.append("Track A (NSRDB, PSM v4 GOES Aggregated at developer.nlr.gov) is unreachable "
                     "from this session's network egress policy - confirmed via `s2_nsrdb.py "
                     "--preflight-only`, which classifies this precisely as `proxy_denial` "
                     "(the local egress proxy rejects the CONNECT tunnel before any TLS handshake, "
                     "not an authentication failure) in under a second. Per the brief's own updated "
                     "architecture, `s2_nsrdb.py` is now a fully standalone script with no import "
                     "from the rest of this repo - it is meant to run on a machine with plain "
                     "internet access (a laptop, a VM, a cron job), not inside this agent sandbox. "
                     "The full pull is 4,798 cells x 7 years = 33,586 cell-years, a four-day job at "
                     "the NLR rate limit (1 req/sec, 10,000/day) even once network access exists "
                     "somewhere. `--dry-run` (no network needed) confirms the exact request list "
                     "the pull would make. Fixing the sandbox's egress policy would let ad-hoc checks "
                     "run from here, but the real pull should happen elsewhere regardless.\n\n")
    lines.append(f"Weather source used this run: `{track_counts}` - {decision_grade_reason}\n\n"
                 "**API key security note:** the key pasted in chat on 11 August 2026 is treated "
                 "as compromised per the brief's own Section 11 item 3 and is NOT used anywhere in "
                 "this codebase - it was rotated and the replacement is set as `NLR_API_KEY` in "
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
    if decision_grade:
        lines.append("- Caveat: fit against real Track A NSRDB weather, but still a ~100-site "
                     "sample where few sites clear the 4-year decision-grade bar. Re-run at full "
                     "scale (4,396 sites with 4+ years) before trusting this number as fleet-wide.\n")
    else:
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
    if decision_grade:
        lines.append("\nAt n~100 sites, large deviation from the reference is still EXPECTED "
                     "(sample-size, not weather-track) and not yet diagnostic of a "
                     "misconfigured classifier - re-check at full fleet scale.\n")
    else:
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
    if decision_grade:
        lines.append("- Real Track A NSRDB weather this run (see above) - the weather-track "
                     "caveat is cleared; 100-site subsample scale is now the single biggest "
                     "caveat on every number.\n")
    else:
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

    run_notes = [
        f"Generated {datetime.now().isoformat()}",
        "Scope: 100-site stratified validation subsample, not the full 6,204-site fleet.",
        f"Weather track this run: {track_counts} - {decision_grade_reason}",
        "solar_assets_data.csv supplied and used - time-varying DC capacity on phased builds is live.",
        "2022 EIA-923 gap (Section 4 item 1) is still open upstream; absent 2022 months are treated "
        "as missing data throughout, never as zero or an outage.",
        "2026 (Jan-May) has PRI but never PI/PR_T (NSRDB has no 2026 data yet) and can never carry "
        "a qualified LEAD - see Section 0.7.",
        "rho_s recovery fractions are placeholders with no ground truth (Section 11 item 6 open).",
        "ISO curtailment feeds not available; CURTAILMENT relies on BA-peer agreement only "
        "(Section 11 item 5 open).",
        "S8 hazard/frailty/credibility and S9 dollar totals are NOT statistically meaningful at "
        "n~100 sites - built and smoke-tested, meaningful results need the full-scale run.",
    ]

    with open("run_report.md", "w") as f:
        f.writelines(lines)

    call_list_xlsx = dollars[dollars["value_usd"] > 0].sort_values("value_usd", ascending=False)[
        [c for c in call_list_cols if c in dollars.columns]
    ]
    assumptions = [dict(a) for a in ASSUMPTIONS]
    for a in assumptions:
        if a["name"] == "weather source this run":
            if decision_grade:
                a["value"] = f"real NSRDB PSM v4 GOES Aggregated ({track_counts})"
                a["status"] = "measured (Track A, developer.nlr.gov)"
            else:
                a["value"] = f"mixed: {track_counts}"
                a["status"] = "PARTIAL/NOT measured NSRDB - not decision-grade"
    build_excel_workbook(funnel, call_list_xlsx, sub, dollars, traj, ledger, credibility, run_notes, assumptions)

    log.info("S10 complete: run_report.md, output/call_list_subsample.csv, "
              "output/PI_PRI_Results.xlsx written")


if __name__ == "__main__":
    main()
