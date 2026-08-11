"""
S11 - Builds explorer.html, a self-contained triage interface (Section 8).

Assembles a compact JSON payload from every prior stage's parquet output
and embeds it directly in the HTML (no fetch(), no server - file:// must
work by double-click). Monthly series are parallel arrays of rounded
numbers, not arrays of objects, per the brief's payload-budget guidance.

SCOPE: built against the 100-site validation subsample, Track B clear-sky
stopgap weather (see run_report.md). Every number in this explorer is
explicitly non-decision-grade until re-run against real NSRDB data at full
fleet scale - the Assumptions panel says so, and so does every dollar
figure's footer, per the brief's "standing caveats" requirement.
"""
import json
import logging
import math

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S11 %(message)s")
log = logging.getLogger("s11")


def r(x, nd=3):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return round(float(x), nd)


def ri(x):
    if x is None or (isinstance(x, float) and (math.isnan(x) or math.isinf(x))):
        return None
    return int(round(float(x)))


def compute_conviction_tier(site_years: pd.DataFrame, traj_row: pd.Series | None) -> str:
    site_years = site_years.sort_values("year")
    if len(site_years) <= 1:
        return "New"
    if traj_row is not None and pd.notna(traj_row.get("beta_excess")) and traj_row["beta_excess"] > 0.03:
        return "Improving"
    # 2026 can never carry a qualified LEAD (no PI - Section 0.7), so it can
    # never be the "latest year" for Chronic/Event purposes. Use the latest
    # year that actually had a PI-based lead determination.
    pi_capable = site_years[site_years["mean_PI"].notna()] if "mean_PI" in site_years else site_years
    if len(pi_capable) == 0:
        return "Healthy"
    latest = pi_capable.iloc[-1]
    prior = pi_capable.iloc[:-1]
    latest_flagged = bool(latest.get("is_lead", False))
    prior_mean_pi = prior["mean_PI"].mean() if len(prior) else np.nan
    if latest_flagged and pd.notna(prior_mean_pi) and prior_mean_pi < config.PI_PRI_DECISION_THRESHOLD:
        return "Chronic"
    if latest_flagged:
        return "Event"
    return "Healthy"


def build_payload() -> dict:
    sites = pd.read_parquet("data/subsample_sites.parquet")
    sig = pd.read_parquet("data/site_month_signatures.parquet")
    dollars = pd.read_parquet("data/site_month_dollars.parquet")
    traj = pd.read_parquet("data/site_trajectory.parquet").set_index("site")
    ledger = pd.read_parquet("data/event_ledger.parquet")
    funnel = pd.read_csv("data/funnel.csv")
    credibility = pd.read_parquet("data/credibility.parquet")
    nsrdb_summary = pd.read_parquet("data/nsrdb_pull_summary.parquet")

    dollars = dollars.sort_values(["site", "month_start"])

    site_year_stats = dollars.groupby(["site", "year"]).agg(
        mean_PI=("PI", "mean"), is_lead=("is_lead", "max")
    ).reset_index()

    site_payloads = []
    for _, srow in sites.iterrows():
        site = srow["site"]
        g = dollars[dollars["site"] == site].sort_values("month_start")
        if len(g) == 0:
            continue

        months = g["month_start"].dt.strftime("%Y-%m").tolist()
        e_act = [r(x, 1) if pd.notna(x) else None for x in g["E_act_mwh"]]
        e_exp = [r(x, 1) if pd.notna(x) else None for x in g["E_exp_mwh"]]
        pi = [r(x, 3) if pd.notna(x) else None for x in g["PI"]]
        pri = [r(x, 3) if pd.notna(x) else None for x in g["PRI"]]
        d_arr = [r(x, 3) if pd.notna(x) else None for x in g["D"]]
        score = [r(x, 3) if pd.notna(x) else None for x in g["score"]]
        sig_final = g["signature_final"].fillna("UNSCORED").tolist()
        gate = g["gate_fired"].fillna("").tolist()
        confidence = g["confidence"].fillna("").tolist()
        value_usd = [r(x, 0) if pd.notna(x) else 0 for x in g["value_usd"]]
        value_usd_quick = [r(x, 0) if pd.notna(x) else 0 for x in g["value_usd_quick"]]
        rec_pct = [r(x, 2) if pd.notna(x) else None for x in g["rec_pct"]]
        weather_track = g["weather_track"].fillna("").tolist()
        benchmark_mode = g["benchmark_mode"].fillna("").tolist()
        peer_count = [ri(x) if pd.notna(x) else None for x in g["peer_count"]]
        peer_radius = [ri(x) if pd.notna(x) else None for x in g["peer_radius_km"]]
        peers_healthy = [ri(x) if pd.notna(x) else None for x in g["peers_healthy"]]
        block_fraction = g["block_fraction"].fillna("").tolist() if "block_fraction" in g else [""] * len(g)
        n_candidates = [ri(x) if pd.notna(x) else 0 for x in g["n_candidates"]] if "n_candidates" in g else [0] * len(g)

        latest = g.iloc[-1]
        fault_months = int(g["fault_flag"].sum())
        episode_count = len(ledger[(ledger["site"] == site) & ledger["signature"].isin(config.FAULT_LEDGER_SIGNATURES)]) \
            if len(ledger) else 0
        top_sig_counts = g.loc[g["fault_flag"], "signature_final"].value_counts()
        top_signature = top_sig_counts.index[0] if len(top_sig_counts) else "NONE"

        recoverable_usd_total = sum(v for v in value_usd if v)
        n_years = g["year"].nunique()
        recoverable_usd_yr = recoverable_usd_total / max(n_years, 1)

        t = traj.loc[site] if site in traj.index else None
        sy = site_year_stats[site_year_stats["site"] == site]
        tier = compute_conviction_tier(sy, t)

        # Current status, not "was ever urgent at some point in 8 years of
        # history" - a site whose 2-year EPC warranty lapsed years ago isn't
        # "warranty-urgent" today.
        warranty_urgent = bool(latest.get("warranty_urgent", False)) if "warranty_urgent" in g else False
        if warranty_urgent and tier not in ("Improving",):
            tier = "Warranty-urgent"

        dq_flags = []
        if bool(srow.get("is_phased_build", False)):
            dq_flags.append("phased_build")
        if srow.get("tracking") in ("Unknown", "Mixed"):
            dq_flags.append("tracking_unknown_or_mixed")
        if srow.get("match_method") == "No match":
            dq_flags.append("no_asset_match")
        if (g["peers_healthy"].fillna(0) < config.PEER_MINIMUM).mean() > 0.5:
            dq_flags.append("peers_lt_4_most_months")
        # g only contains reported months by construction (S4 merges against
        # production[production["reported"]]), so presence in g IS "reported".
        has_2022 = (g["year"] == 2022).any()
        has_2021_2023 = (g["year"] == 2021).any() and (g["year"] == 2023).any()
        if has_2021_2023 and not has_2022:
            dq_flags.append("2022_data_gap")
        if (g["weather_track"] == "B_clearsky_stopgap").any():
            dq_flags.append("track_b_stopgap")

        cred = credibility[credibility["site"] == site]

        site_payloads.append(dict(
            site=site, state=srow.get("state"), operator=srow.get("operator"),
            utility=srow.get("utility"), county=srow.get("county"), ba=srow.get("ba"),
            plant_id=r(srow.get("plant_id"), 0), mwac=r(srow.get("mwac"), 2), mwdc=r(srow.get("mwdc"), 2),
            dcac=r(srow.get("dcac"), 3), tracking=srow.get("tracking"), module=srow.get("module"),
            tilt=r(srow.get("tilt"), 1), azimuth=r(srow.get("azimuth"), 1),
            lat=r(srow.get("lat"), 4), lon=r(srow.get("lon"), 4),
            cod=str(srow.get("cod"))[:10] if pd.notna(srow.get("cod")) else None,
            years_present=ri(srow.get("years_present")),
            months=months, e_act=e_act, e_exp=e_exp, pi=pi, pri=pri, d=d_arr, score=score,
            signature=sig_final, gate=gate, confidence=confidence,
            value_usd=value_usd, value_usd_quick=value_usd_quick, rec_pct=rec_pct,
            weather_track=weather_track, benchmark_mode=benchmark_mode,
            peer_count=peer_count, peer_radius_km=peer_radius, peers_healthy=peers_healthy,
            block_fraction=block_fraction, n_candidates=n_candidates,
            latest_pi=r(latest.get("PI"), 3), latest_pri=r(latest.get("PRI"), 3), latest_d=r(latest.get("D"), 3),
            beta=r(t["beta"], 4) if t is not None else None,
            beta_se=r(t["beta_se"], 4) if t is not None else None,
            beta_t=r(t["beta_t"], 2) if t is not None else None,
            beta_excess=r(t["beta_excess"], 4) if t is not None else None,
            decision_grade=bool(t["decision_grade"]) if t is not None else False,
            excess_category=t["excess_category"] if t is not None else None,
            fault_months=fault_months, episode_count=episode_count, top_signature=top_signature,
            conviction_tier=tier, warranty_urgent=warranty_urgent,
            recoverable_usd_yr=r(recoverable_usd_yr, 0),
            recoverable_mwh_yr=r(sum(g["gross_gap_mwh"].fillna(0)) / max(n_years, 1), 1) if "gross_gap_mwh" in g else None,
            data_quality_flags=dq_flags,
            credibility=[dict(signature=row["signature"], lambda_shrunk=r(row["lambda_shrunk"], 4),
                              Z=r(row["credibility_Z"], 3), pool=row["pool_level"])
                        for _, row in cred.iterrows()],
        ))

    ledger_out = []
    for _, row in ledger.iterrows():
        ledger_out.append(dict(
            site=row["site"], year=ri(row["year"]), signature=row["signature"],
            months=ri(row["months"]), episodes=ri(row["episodes"]) if pd.notna(row["episodes"]) else None,
            exposure_months=ri(row["exposure_months"]), age_start=r(row["age_start"], 1),
            mwh_lost=r(row.get("mwh_lost"), 1), usd_lost=r(row.get("usd_lost"), 0),
            max_severity=r(row["max_severity"], 3),
        ))

    n_leads = sum(1 for s in site_payloads if s["conviction_tier"] in ("Chronic", "Event"))
    n_high_conviction = sum(1 for s in site_payloads if s["conviction_tier"] == "Chronic")
    total_recoverable_usd_yr = sum(s["recoverable_usd_yr"] or 0 for s in site_payloads)
    total_recoverable_mwh_yr = sum(s["recoverable_mwh_yr"] or 0 for s in site_payloads)

    all_pi = [v for s in site_payloads for v in s["pi"] if v is not None]
    all_pri = [v for s in site_payloads for v in s["pri"] if v is not None]

    sig_counts = {}
    year_sig_counts = {}
    for s in site_payloads:
        for m, sg in zip(s["months"], s["signature"]):
            if sg in ("NONE", "WATCH_NOT_A_FAULT", "UNSCORED"):
                continue
            sig_counts[sg] = sig_counts.get(sg, 0) + 1
            yr = m[:4]
            year_sig_counts.setdefault(yr, {})
            year_sig_counts[yr][sg] = year_sig_counts[yr].get(sg, 0) + 1

    hazard = pd.read_parquet("data/hazard_by_age_band.parquet")
    hazard_out = [dict(signature=row["signature"], age_band=str(row["age_band"]),
                       rate=r(row["rate_per_exposure_year"], 3))
                  for _, row in hazard.iterrows() if pd.notna(row["rate_per_exposure_year"])]

    payload = dict(
        meta=dict(
            generated_at=pd.Timestamp.now().isoformat(),
            scope="100-site stratified VALIDATION SUBSAMPLE, not the full 6,204-site fleet",
            weather_track_summary=nsrdb_summary["track"].value_counts().to_dict(),
            decision_grade=False,
            decision_grade_reason="Track B clear-sky stopgap weather (NSRDB unreachable from the "
                                  "build environment) and subsample scale, not full fleet",
            ppa_usd_per_mwh=config.PPA_USD_PER_MWH,
            pi_pri_threshold=config.PI_PRI_DECISION_THRESHOLD,
            assumptions=[
                dict(name="PPA", value="40.0 USD/MWh", status="fixed by Carlos, Aug 2026"),
                dict(name="gamma (c-Si)", value="-0.0037 /degC", status="measured (IEC/lab)"),
                dict(name="gamma (CdTe)", value="-0.0028 /degC", status="measured (IEC/lab)"),
                dict(name="d (c-Si)", value="0.005 /yr", status="assumed structural prior, fixed by design"),
                dict(name="d (CdTe)", value="0.004 /yr", status="assumed structural prior, fixed by design"),
                dict(name="static loss stack L", value="0.86", status="assumed"),
                dict(name="inverter efficiency", value="0.985", status="assumed"),
                dict(name="rho_s (all signatures)", value="see Action Map", status="PLACEHOLDER, no ground truth yet"),
                dict(name="warranty terms", value="2y EPC / 5-10y inverter / 10-12y module / 25y perf.", status="assumed default, not contractual"),
                dict(name="weather source this run", value="pvlib clear-sky (Ineichen) stopgap", status="NOT measured NSRDB - not decision-grade"),
            ],
        ),
        funnel=funnel.to_dict(orient="records"),
        kpi=dict(
            scoreable_sites_subsample=len(site_payloads),
            scoreable_sites_fleet=6204,
            gw_ac_fleet=113.8,
            site_months_scored=sum(len(s["months"]) for s in site_payloads),
            leads=n_leads, high_conviction=n_high_conviction,
            recoverable_mwh_yr=r(total_recoverable_mwh_yr, 0),
            recoverable_usd_yr=r(total_recoverable_usd_yr, 0),
            pi_p25=r(np.percentile(all_pi, 25), 3) if all_pi else None,
            pi_p50=r(np.percentile(all_pi, 50), 3) if all_pi else None,
            pi_p75=r(np.percentile(all_pi, 75), 3) if all_pi else None,
            pri_p25=r(np.percentile(all_pri, 25), 3) if all_pri else None,
            pri_p50=r(np.percentile(all_pri, 50), 3) if all_pri else None,
            pri_p75=r(np.percentile(all_pri, 75), 3) if all_pri else None,
        ),
        signature_counts=sig_counts,
        year_signature_counts=year_sig_counts,
        hazard=hazard_out,
        sites=site_payloads,
        ledger=ledger_out,
    )
    return payload


def sanitize(obj):
    """Recursively replace NaN/NaT/pandas-missing with None. json.dumps
    otherwise emits the bare token NaN, which is not valid JSON and breaks
    JSON.parse in the browser (float('nan') is not caught by the per-field
    rounding helpers for string/passthrough fields)."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, float) and math.isnan(obj):
        return None
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj


def main():
    payload = build_payload()
    payload = sanitize(payload)
    payload_json = json.dumps(payload, separators=(",", ":"))
    size_mb = len(payload_json.encode("utf-8")) / 1e6
    log.info("payload: %d sites, %.2f MB", len(payload["sites"]), size_mb)
    if size_mb > 25:
        log.warning("payload exceeds the 25MB budget - consider sharding (not done here)")

    template = open("explorer_template.html").read()
    html = template.replace("__PAYLOAD_JSON__", payload_json)

    with open("explorer.html", "w") as f:
        f.write(html)
    log.info("wrote explorer.html (%.2f MB)", len(html.encode("utf-8")) / 1e6)


if __name__ == "__main__":
    main()
