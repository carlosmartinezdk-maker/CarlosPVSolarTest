"""
S11 - Builds explorer.html, a self-contained triage interface (Section 8).

Assembles a compact JSON payload from every prior stage's parquet output
and embeds it directly in the HTML (no fetch(), no server - file:// must
work by double-click). Monthly series are parallel arrays of rounded
numbers, not arrays of objects, per the brief's payload-budget guidance.

SCOPE: built against the 100-site validation subsample (see run_report.md
for which weather track - real Track A NSRDB or Track B clear-sky stopgap -
this run actually used). `meta.decision_grade` reflects the real
`data/nsrdb_pull_summary.parquet` track mix rather than assuming Track B,
per the brief's "standing caveats" requirement.
"""
import json
import logging
import math
import os

import numpy as np
import pandas as pd
import yaml

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


def track_mix_decision_grade(track_counts: dict) -> tuple[bool, str]:
    """Single source of truth for 'is this run's weather decision-grade',
    read from the actual data/nsrdb_pull_summary.parquet track mix instead
    of assuming Track B. Used by S10 (run_report.md, xlsx Notes) and S11
    (explorer meta) so both honestly reflect real vs. stopgap per run."""
    n_cell_years = sum(track_counts.values())
    pct_real = track_counts.get("A", 0) / n_cell_years if n_cell_years else 0.0
    if pct_real == 1.0:
        return True, (
            f"100% Track A (real NSRDB PSM v4 GOES Aggregated weather, {n_cell_years} "
            "cell-years) this run - the weather-track caveat is cleared. Still a 100-site "
            "stratified validation subsample, not the full 6,204-site fleet."
        )
    return False, (
        f"Weather track mix this run: {track_counts} - {pct_real:.0%} real Track A NSRDB "
        "weather, remainder Track B clear-sky (pvlib Ineichen) stopgap. Not decision-grade "
        "until 100% Track A."
    )


def pi_bias_diagnostic(idx: pd.DataFrame, sites: pd.DataFrame) -> dict:
    """Explorer v2 Part A2: regress monthly PI on month-of-year and latitude.
    An unbiased physical model should show no systematic seasonal or
    latitudinal pattern - if PI dips every winter or moves with latitude,
    that's model bias (most likely the static loss stack L, see config.py),
    not real fleet behaviour. Report the finding, don't guess a new L
    without evidence of the right value."""
    import statsmodels.api as sm
    d = idx.merge(sites[["site", "lat"]], on="site", how="left").dropna(subset=["PI", "lat"])
    d = d.copy()
    d["month"] = pd.to_datetime(d["month_start"]).dt.month
    month_dummies = pd.get_dummies(d["month"], prefix="m", drop_first=True).astype(float)
    X = sm.add_constant(pd.concat([d[["lat"]], month_dummies], axis=1))
    model = sm.OLS(d["PI"], X, missing="drop").fit()
    by_month = d.groupby("month")["PI"].mean().round(3).to_dict()
    return dict(
        n=len(d),
        lat_coef=r(model.params["lat"], 5), lat_pvalue=r(model.pvalues["lat"], 4),
        pi_by_month=by_month,
        winter_summer_gap=r(max(by_month.get(m, 0) for m in (10, 11)) -
                             min(by_month.get(m, 1) for m in (1, 12)), 3),
        biased=bool(model.pvalues["lat"] < 0.05),
    )


def load_pricing(path: str = "pricing.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


# --------------------------------------------------------------------------
# Explorer v2 Part E - service routing layer
# --------------------------------------------------------------------------
QUADRANT_BASE_OFFERING = {
    "plant_specific_fault": "Recurrent Inspection",
    "weather_or_curtailment": "SCADA Monitoring",
    "peer_group_distant": "Solar SaaS",
    "normal_conditions": "Solar SaaS",
}


def compute_quadrant(pi, pri, threshold=None) -> str | None:
    """Carlos's PI/PRI matrix (brief Part E). threshold=0.92 on both."""
    threshold = config.PI_PRI_DECISION_THRESHOLD if threshold is None else threshold
    if pi is None or pri is None:
        return None
    pi_low, pri_low = pi < threshold, pri < threshold
    if pi_low and pri_low:
        return "plant_specific_fault"
    if pi_low and not pri_low:
        return "weather_or_curtailment"
    if not pi_low and pri_low:
        return "peer_group_distant"
    return "normal_conditions"


def trailing12_modal_quadrant(months: list, pi_arr: list, pri_arr: list, threshold=None) -> str | None:
    """A single odd month should not reroute a site - trailing-12-month
    modal quadrant is what actually drives routing; the latest-month
    quadrant is shown alongside for urgency only (brief Part E)."""
    quads = [compute_quadrant(pi_arr[i], pri_arr[i], threshold) for i in range(len(months))][-12:]
    quads = [q for q in quads if q is not None]
    if not quads:
        return None
    return max(set(quads), key=quads.count)


def compute_routing(pi_latest, pri_latest, quadrant_trailing12, beta_excess, beta_t,
                     age_years, warranty_active, eal_top_decile, pricing) -> dict:
    """Two-step routing (brief Part E section 7): quadrant gives the base
    offering, then trajectory/age/warranty overlay adds RVM, warranty claim
    support, or the SCADA prevention sale. A site can carry more than one
    offering."""
    quadrant_latest = compute_quadrant(pi_latest, pri_latest)
    base_offering = QUADRANT_BASE_OFFERING.get(quadrant_trailing12)
    offerings = [base_offering] if base_offering else []
    rvm = pricing["rvm_eligibility"]
    slope_significant = beta_excess is not None and beta_t is not None and abs(beta_t) >= abs(rvm["beta_t_threshold"])
    declining = slope_significant and beta_excess < rvm["beta_excess_threshold"]

    warranty_claim = bool(warranty_active and declining)
    rvm_eligible = bool(declining and not warranty_active and age_years is not None
                         and age_years >= rvm["min_age_years"])
    if warranty_claim:
        offerings = ["Warranty Claim Support"] + offerings  # highest priority - carries a deadline
    elif rvm_eligible:
        offerings.append("RVM")
    if eal_top_decile and "SCADA Monitoring" not in offerings:
        offerings.append("SCADA Monitoring")  # the prevention sale
    return dict(
        quadrant_latest=quadrant_latest, quadrant_trailing12=quadrant_trailing12,
        base_offering=base_offering, rvm_eligible=rvm_eligible, warranty_active=bool(warranty_active),
        warranty_claim_support=warranty_claim, recommended_offerings=offerings,
    )


# --------------------------------------------------------------------------
# Explorer v2 Part F - ROI engine (PRICING_AND_ROI_ADDENDUM.md)
# --------------------------------------------------------------------------
def repair_cost(signature: str, severity, mwdc, pricing) -> dict:
    """addendum section 3: repair_cost = mobilisation + unit_rate x
    affected_mwdc, affected_mwdc = mwdc x severity (block_fraction for a
    fitted BLOCK_OUTAGE, else D). ESTIMATE, not a vendor quote."""
    rc = pricing["repair_costs"]["by_signature"].get(signature)
    if rc is None or severity is None or mwdc is None:
        return dict(repair_cost_usd=None, affected_mwdc=None, repair_uneconomic=False,
                    repair_cost_source="ESTIMATE")
    affected = mwdc * severity
    cost = rc["mobilisation_usd"] + rc["usd_per_mwdc_affected"] * affected
    cap = pricing["repair_costs"]["uneconomic_repair_fraction_of_capex"] * pricing["repair_costs"]["capex_usd_per_mwdc"] * mwdc
    return dict(repair_cost_usd=r(cost, 0), affected_mwdc=r(affected, 3),
                repair_uneconomic=bool(cost > cap), repair_cost_source="ESTIMATE")


def remediation_timeline(signature: str, pricing) -> dict:
    """addendum section 5: t_detect = data_lag + review_cadence/2;
    t_total = t_detect + t_remediate(signature)."""
    t = pricing["timelines"]
    t_detect = t["data_lag_months"] + t["review_cadence_months"] / 2
    t_remediate = t["remediation_months"].get(signature)
    if t_remediate is None:
        return dict(t_detect_months=r(t_detect, 2), t_remediate_months=None, t_total_months=None)
    t_total = t_detect + t_remediate
    return dict(t_detect_months=r(t_detect, 2), t_remediate_months=r(t_remediate, 2), t_total_months=r(t_total, 2))


def detection_value(recoverable_usd_yr, t_total_months, pricing) -> dict:
    """addendum section 5: V_detect_year1 prorates by the detection +
    remediation clock; steady-state is the full recoverable value."""
    conv = pricing["conversion"]["detection_to_remediation"]
    steady = (recoverable_usd_yr or 0) * conv
    if t_total_months is None:
        return dict(v_detect_year1_usd=r(steady, 0), v_detect_steady_usd=r(steady, 0))
    year1 = steady * max(0, 1 - t_total_months / 12)
    return dict(v_detect_year1_usd=r(year1, 0), v_detect_steady_usd=r(steady, 0))


def cost_of_inaction(recoverable_usd_yr, beta_excess, beta_t, horizon_years, discount_rate, pricing) -> float | None:
    """addendum: loss_h = current_gap x (1+|beta_excess|)^h, discounted.
    Only compound a beta whose |t| >= threshold (Part A5/test 37) - never
    compound a noise slope into a multi-year dollar figure."""
    if recoverable_usd_yr is None:
        return None
    slope_significant = beta_excess is not None and beta_t is not None and \
        abs(beta_t) >= config.BETA_T_SIGNIFICANCE_THRESHOLD
    growth = abs(beta_excess) if (slope_significant and beta_excess is not None and beta_excess < 0) else 0.0
    total = 0.0
    for h in range(1, horizon_years + 1):
        loss_h = recoverable_usd_yr * (1 + growth) ** h
        total += loss_h / (1 + discount_rate) ** h
    return r(total, 0)


def compute_roi(recoverable_usd_yr, offerings, mwdc, signature, severity, beta_excess, beta_t, pricing) -> dict:
    off = pricing["offerings"]
    fee = 0.0
    fee_sources = []
    if "Solar SaaS" in offerings:
        fee += off["solar_saas"]["usd_per_mwdc_year"] * (mwdc or 0); fee_sources.append("solar_saas")
    if "SCADA Monitoring" in offerings:
        fee += off["scada_monitoring"]["usd_per_mwdc_year"] * (mwdc or 0); fee_sources.append("scada_monitoring")
    if "Recurrent Inspection" in offerings:
        insp = off["solar_inspection"]
        fee += insp["usd_per_mwdc_inspected"] * (mwdc or 0) * insp["inspections_per_year"]
        fee_sources.append("solar_inspection")

    rc = repair_cost(signature, severity, mwdc, pricing)
    rvm_fee_gross = rvm_fee_incremental = None
    if "RVM" in offerings and rc["repair_cost_usd"] is not None and not rc["repair_uneconomic"]:
        markup = off["rvm"]["markup_pct_of_repair_spend"]
        rvm_fee_gross = r(rc["repair_cost_usd"] * (1 + markup), 0)
        rvm_fee_incremental = r(rc["repair_cost_usd"] * markup, 0)  # addendum sec 4: default headline

    timeline = remediation_timeline(signature, pricing)
    value = detection_value(recoverable_usd_yr, timeline["t_total_months"], pricing)
    horizon = pricing["horizon_years"]
    coi = cost_of_inaction(recoverable_usd_yr, beta_excess, beta_t, horizon, pricing["discount_rate"], pricing)

    ssi_cost = fee * horizon  # simple undiscounted sum for the ratio; net_benefit below discounts CoI already
    net_benefit = (coi or 0) - ssi_cost
    roi_multiple = (coi / ssi_cost) if (coi and ssi_cost > 0) else None
    payback_months = (12 * fee / value["v_detect_steady_usd"]) if (fee > 0 and value["v_detect_steady_usd"]) else None
    ratio_suppressed = bool(roi_multiple is not None and roi_multiple > pricing["ratio_suppression_threshold"])

    return dict(
        annual_fee_usd=r(fee, 0) if fee else 0, pricing_source="confirmed" if fee_sources else None,
        repair_cost_usd=rc["repair_cost_usd"], repair_cost_source=rc["repair_cost_source"],
        repair_uneconomic=rc["repair_uneconomic"],
        rvm_fee_gross_usd=rvm_fee_gross, rvm_fee_incremental_usd=rvm_fee_incremental,
        t_detect_months=timeline["t_detect_months"], t_remediate_months=timeline["t_remediate_months"],
        v_detect_year1_usd=value["v_detect_year1_usd"], v_detect_steady_usd=value["v_detect_steady_usd"],
        cost_of_inaction_usd=coi, net_benefit_usd=r(net_benefit, 0) if coi is not None else None,
        roi_multiple=None if ratio_suppressed else (r(roi_multiple, 1) if roi_multiple is not None else None),
        ratio_suppressed=ratio_suppressed, payback_months=r(payback_months, 1) if payback_months is not None else None,
    )


def compute_conviction_tier(site_years: pd.DataFrame, traj_row: pd.Series | None,
                             recoverable_usd_yr: float = 0.0, excess_category: str | None = None) -> str:
    """Explorer v2 Part A5/A6: tier must consume trajectory AND dollars, and
    a beta with |t| < BETA_T_SIGNIFICANCE_THRESHOLD is noise, not a slope -
    it may never drive "Improving" (test 37). No site may end up "Healthy"
    while carrying recoverable value or an accelerating-loss trajectory
    (test 36) - that combination gets reclassified to "Event" below."""
    site_years = site_years.sort_values("year")
    if len(site_years) <= 1:
        tier = "New"
    else:
        beta_significant = (traj_row is not None and pd.notna(traj_row.get("beta_excess"))
                             and pd.notna(traj_row.get("beta_t"))
                             and abs(traj_row["beta_t"]) >= config.BETA_T_SIGNIFICANCE_THRESHOLD)
        if beta_significant and traj_row["beta_excess"] > 0.03:
            tier = "Improving"
        else:
            # 2026 can never carry a qualified LEAD (no PI - Section 0.7), so
            # it can never be the "latest year" for Chronic/Event purposes.
            # Use the latest year that actually had a PI-based lead
            # determination.
            pi_capable = site_years[site_years["mean_PI"].notna()] if "mean_PI" in site_years else site_years
            if len(pi_capable) == 0:
                tier = "Healthy"
            else:
                latest = pi_capable.iloc[-1]
                prior = pi_capable.iloc[:-1]
                latest_flagged = bool(latest.get("is_lead", False))
                prior_mean_pi = prior["mean_PI"].mean() if len(prior) else np.nan
                if latest_flagged and pd.notna(prior_mean_pi) and prior_mean_pi < config.PI_PRI_DECISION_THRESHOLD:
                    tier = "Chronic"
                elif latest_flagged:
                    tier = "Event"
                else:
                    tier = "Healthy"

    if tier == "Healthy" and (
        (recoverable_usd_yr or 0) > 0 or excess_category == "accelerating_loss"
    ):
        tier = "Event"
    return tier


def build_payload() -> dict:
    sites = pd.read_parquet("data/subsample_sites.parquet")
    sig = pd.read_parquet("data/site_month_signatures.parquet")
    dollars = pd.read_parquet("data/site_month_dollars.parquet")
    traj = pd.read_parquet("data/site_trajectory.parquet").set_index("site")
    ledger = pd.read_parquet("data/event_ledger.parquet")
    funnel = pd.read_csv("data/funnel.csv")
    credibility = pd.read_parquet("data/credibility.parquet")
    nsrdb_summary = pd.read_parquet("data/nsrdb_pull_summary.parquet")
    idx = pd.read_parquet("data/site_month_indices.parquet")
    pi_bias = pi_bias_diagnostic(idx, sites)
    pricing = load_pricing()

    dollars = dollars.sort_values(["site", "month_start"])

    site_year_stats = dollars.groupby(["site", "year"]).agg(
        mean_PI=("PI", "mean"), is_lead=("is_lead", "max")
    ).reset_index()

    # Part E prevention overlay: "EAL in the top decile of peers". No
    # single $ EAL column exists yet in S8's output, so this is a proxy
    # (shrunk event rate x severity, summed across signatures) - directionally
    # right for ranking, not a claimed dollar figure. Documented as such.
    if len(credibility):
        eal_proxy = (credibility.assign(_eal=credibility["lambda_shrunk"] * credibility["tau_s"])
                     .groupby("site")["_eal"].sum())
        eal_decile_cutoff = eal_proxy.quantile(0.9)
    else:
        eal_proxy = pd.Series(dtype=float)
        eal_decile_cutoff = None

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
        # Explorer v2 Part A1: "latest" PI/PRI must mean the latest SCORED
        # month, not the last array slot - 2026 has no irradiance (Section
        # 0.7) so its months are never PI-scored, and reading g.iloc[-1]
        # silently nulled latest_pi/latest_pri for every site (test 34).
        scored = g[g["PI"].notna()]
        if len(scored):
            latest_scored = scored.iloc[-1]
            latest_scored_month = latest_scored["month_start"].strftime("%Y-%m")
            months_since_last_scored = (
                (latest["month_start"].year - latest_scored["month_start"].year) * 12
                + (latest["month_start"].month - latest_scored["month_start"].month)
            )
        else:
            latest_scored = None
            latest_scored_month = None
            months_since_last_scored = None
        stale = bool(months_since_last_scored is not None
                     and months_since_last_scored >= config.STALE_MONTHS_THRESHOLD)
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
        excess_category = t["excess_category"] if t is not None else None
        tier = compute_conviction_tier(sy, t, recoverable_usd_yr, excess_category)

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

        # Part E/F: routing + ROI. Severity for repair costing comes from
        # the most recent fault month - block_fraction when a BLOCK_OUTAGE
        # fraction was fitted, D otherwise (addendum section 3).
        age_years = srow.get("plant_age")
        age_years = None if pd.isna(age_years) else float(age_years)
        warranty_active = bool(age_years is not None and age_years < config.WARRANTY_DEFAULTS_YEARS["module_performance"])
        fault_idxs = [i for i, sgv in enumerate(sig_final) if sgv not in ("NONE", "UNSCORED", "WATCH_NOT_A_FAULT")]
        if fault_idxs:
            fi = fault_idxs[-1]
            fault_sig = sig_final[fi]
            severity = block_fraction[fi] if (fault_sig == "BLOCK_OUTAGE" and block_fraction[fi]) else d_arr[fi]
            if isinstance(severity, str):
                severity = None
        else:
            fault_sig, severity = top_signature, None
        quadrant_trailing12 = trailing12_modal_quadrant(months, pi, pri)
        site_eal = eal_proxy.get(site, 0.0)
        eal_top_decile = bool(eal_decile_cutoff is not None and site_eal >= eal_decile_cutoff and site_eal > 0)
        routing = compute_routing(
            pi_latest=latest_scored.get("PI") if latest_scored is not None else None,
            pri_latest=latest_scored.get("PRI") if latest_scored is not None else None,
            quadrant_trailing12=quadrant_trailing12,
            beta_excess=t["beta_excess"] if t is not None else None,
            beta_t=t["beta_t"] if t is not None else None,
            age_years=age_years, warranty_active=warranty_active,
            eal_top_decile=eal_top_decile, pricing=pricing,
        )
        roi = compute_roi(
            recoverable_usd_yr=recoverable_usd_yr, offerings=routing["recommended_offerings"],
            mwdc=srow.get("mwdc"), signature=fault_sig, severity=severity,
            beta_excess=t["beta_excess"] if t is not None else None,
            beta_t=t["beta_t"] if t is not None else None, pricing=pricing,
        )

        site_payloads.append(dict(
            **routing, **roi,
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
            latest_pi=r(latest_scored.get("PI"), 3) if latest_scored is not None else None,
            latest_pri=r(latest_scored.get("PRI"), 3) if latest_scored is not None else None,
            latest_d=r(latest_scored.get("D"), 3) if latest_scored is not None else None,
            latest_scored_month=latest_scored_month,
            months_since_last_scored=months_since_last_scored,
            stale=stale,
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

    track_counts = nsrdb_summary["track"].value_counts().to_dict()
    decision_grade, decision_grade_reason = track_mix_decision_grade(track_counts)
    if decision_grade:
        weather_source_assumption = f"real NSRDB PSM v4 GOES Aggregated ({track_counts})"
        weather_source_status = "measured (Track A, developer.nlr.gov)"
    else:
        weather_source_assumption = f"mixed: {track_counts}"
        weather_source_status = "PARTIAL/NOT measured NSRDB - not decision-grade"

    payload = dict(
        meta=dict(
            generated_at=pd.Timestamp.now().isoformat(),
            scope="100-site stratified VALIDATION SUBSAMPLE, not the full 6,204-site fleet",
            weather_track_summary=track_counts,
            decision_grade=decision_grade,
            decision_grade_reason=decision_grade_reason,
            pi_provisional=pi_bias["biased"],
            pi_bias_note=(
                f"PI regressed on month-of-year and latitude (n={pi_bias['n']}): latitude "
                f"coefficient {pi_bias['lat_coef']} (p={pi_bias['lat_pvalue']}), "
                f"winter-vs-autumn gap {pi_bias['winter_summer_gap']}. This is model bias "
                "(likely the static loss stack L, see config.py), not fleet behaviour. "
                "Treat PI as provisional and lead with PRI until recalibrated."
                if pi_bias["biased"] else
                "No significant seasonal/latitudinal PI bias detected this run."
            ),
            ppa_usd_per_mwh=config.PPA_USD_PER_MWH,
            pi_pri_threshold=config.PI_PRI_DECISION_THRESHOLD,
            assumptions=[
                dict(name="PPA", value="40.0 USD/MWh", status="fixed by Carlos, Aug 2026"),
                dict(name="gamma (c-Si)", value="-0.0037 /degC", status="measured (IEC/lab)"),
                dict(name="gamma (CdTe)", value="-0.0028 /degC", status="measured (IEC/lab)"),
                dict(name="d (c-Si)", value="0.005 /yr", status="assumed structural prior, fixed by design"),
                dict(name="d (CdTe)", value="0.004 /yr", status="assumed structural prior, fixed by design"),
                dict(name="static loss stack L", value="0.86", status="assumed - PI provisional pending A2 recalibration" if pi_bias["biased"] else "assumed"),
                dict(name="inverter efficiency", value="0.985", status="assumed"),
                dict(name="rho_s (all signatures)", value="see Action Map", status="PLACEHOLDER, no ground truth yet"),
                dict(name="warranty terms", value="2y EPC / 5-10y inverter / 10-12y module / 25y perf.", status="assumed default, not contractual"),
                dict(name="weather source this run", value=weather_source_assumption, status=weather_source_status),
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
