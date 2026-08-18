"""
S11 - Builds explorer.html, a self-contained triage interface (Section 8).

Assembles a compact JSON payload from every prior stage's parquet output
and embeds it directly in the HTML (no fetch(), no server - file:// must
work by double-click). Monthly series are parallel arrays of rounded
numbers, not arrays of objects, per the brief's payload-budget guidance.

SCOPE: built against whatever site set data/subsample_sites.parquet holds
this run - a fixed 100-site stratified subsample, a geographic expansion
batch, or their union (see run_report.md and meta.scope for the real
count/composition each run). `meta.decision_grade` reflects the real
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


def describe_scope(sub: pd.DataFrame) -> str:
    """Dynamic scope description - the analysis set has grown past a fixed
    100-site subsample (now includes geographically-clustered expansion
    batches like CA/NC/SC), so scope text must reflect the real site count
    and composition each run, not a hardcoded number (test: no stale
    "100-site" strings survive a scale-up)."""
    n = len(sub)
    top_states = sub["state"].value_counts().head(3)
    top_str = ", ".join(f"{st} ({ct})" for st, ct in top_states.items())
    n_other_states = sub["state"].nunique() - len(top_states)
    other_str = f", {n_other_states} other states" if n_other_states > 0 else ""
    return f"{n}-site sample ({top_str}{other_str}), not the full 6,204-site fleet"


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
            "cell-years) this run - the weather-track caveat is cleared. Still a "
            "validation-scale sample, not the full 6,204-site fleet."
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


def _customer_roi_payback_months(v_year1, v_steady, fee_annual, repair_outlay, horizon_years):
    """Month the customer's cumulative benefit first equals or exceeds their
    cumulative cost - repair_outlay lands undiscounted in month 1 alongside
    the first month's fee/recovered-value slice, per §2.2's cash-flow rule."""
    cum_benefit, cum_cost = 0.0, repair_outlay
    for month in range(1, horizon_years * 12 + 1):
        year_idx = (month - 1) // 12 + 1
        cum_benefit += (v_year1 if year_idx == 1 else v_steady) / 12
        cum_cost += fee_annual / 12
        if cum_benefit >= cum_cost:
            return month
    return None


def _customer_roi_irr(v_year1, v_steady, fee_annual, repair_outlay, horizon_years):
    """Discount rate where net_benefit = 0 - repair_outlay stays undiscounted
    (it lands in year 1 regardless of rate) while benefit/fees discount with
    r, matching §2.2's own definitions for benefit and cost. Bisection over
    a wide bracket; returns None if no root exists in range (e.g. the site
    never breaks even, or breaks even so fast even a very high rate can't
    erase the surplus)."""
    def npv(rate):
        b = sum((v_year1 if h == 1 else v_steady) / (1 + rate) ** h for h in range(1, horizon_years + 1))
        f = sum(fee_annual / (1 + rate) ** h for h in range(1, horizon_years + 1))
        return b - f - repair_outlay
    lo, hi = -0.9, 20.0
    npv_lo, npv_hi = npv(lo), npv(hi)
    if npv_lo * npv_hi > 0:
        return None
    for _ in range(60):
        mid = (lo + hi) / 2
        npv_mid = npv(mid)
        if abs(npv_mid) < 1e-6:
            return mid
        if (npv_lo * npv_mid) < 0:
            hi = mid
        else:
            lo, npv_lo = mid, npv_mid
    return (lo + hi) / 2


def compute_customer_roi(v_detect_year1, v_detect_steady, fee_annual, repair_cost_usd,
                          repair_uneconomic, rvm_active, horizon_years, discount_rate) -> dict:
    """RECOVERY_BENCHMARK_AND_CUSTOMER_ROI.md §2.2 - what the CUSTOMER
    actually pays (SSI fees AND repair spend), not just our fee. Kept as
    its own field namespace (customer_roi_*) rather than overwriting the
    existing SSI-fee-only roi_multiple/net_benefit_usd/payback_months -
    the two answer different questions and, per §1.3's "never sum them"
    precedent for the benchmark toggle, must never be confused for each
    other either.

    §2.1's own reference run: benefit $601.6M, SSI fees $42.3M, repair
    $182.5M, total cost $224.7M, net $376.9M, ROI 2.7x - repair is 81% of
    what the customer pays, which is the whole point of this section."""
    if repair_uneconomic:
        return dict(customer_roi_benefit_usd=None, customer_roi_ssi_fees_usd=None,
                     customer_roi_repair_outlay_usd=None, customer_roi_cost_usd=None,
                     customer_roi_net_benefit_usd=None, customer_roi_multiple=None,
                     customer_roi_payback_months=None, customer_roi_irr=None,
                     customer_roi_excluded=True)
    benefit = sum((v_detect_year1 if h == 1 else v_detect_steady) / (1 + discount_rate) ** h
                  for h in range(1, horizon_years + 1))
    ssi_fees = sum(fee_annual / (1 + discount_rate) ** h for h in range(1, horizon_years + 1))
    repair_outlay = (repair_cost_usd or 0) * (1.20 if rvm_active else 1.00)
    customer_cost = ssi_fees + repair_outlay
    net_benefit = benefit - customer_cost
    roi_multiple = (benefit / customer_cost) if customer_cost > 0 else None
    payback = _customer_roi_payback_months(v_detect_year1, v_detect_steady, fee_annual, repair_outlay, horizon_years)
    irr = _customer_roi_irr(v_detect_year1, v_detect_steady, fee_annual, repair_outlay, horizon_years)
    return dict(
        customer_roi_benefit_usd=r(benefit, 0), customer_roi_ssi_fees_usd=r(ssi_fees, 0),
        customer_roi_repair_outlay_usd=r(repair_outlay, 0), customer_roi_cost_usd=r(customer_cost, 0),
        customer_roi_net_benefit_usd=r(net_benefit, 0),
        customer_roi_multiple=r(roi_multiple, 2) if roi_multiple is not None else None,
        customer_roi_payback_months=payback,
        customer_roi_irr=r(irr, 3) if irr is not None else None,
        customer_roi_excluded=False,
    )


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

    # §2: customer-side ROI - includes what the customer pays for repairs,
    # not just our fee. "RVM coordinates" = RVM is one of the recommended
    # offerings (same condition as the rvm_fee_* fields above).
    croi = compute_customer_roi(
        v_detect_year1=value["v_detect_year1_usd"], v_detect_steady=value["v_detect_steady_usd"],
        fee_annual=fee, repair_cost_usd=rc["repair_cost_usd"], repair_uneconomic=rc["repair_uneconomic"],
        rvm_active="RVM" in offerings, horizon_years=horizon, discount_rate=pricing["discount_rate"],
    )

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
        **croi,
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

    reliability_site_lookup = load_reliability_site_lookup()

    # Part 1: switchable recovery benchmark (RECOVERY_BENCHMARK_AND_CUSTOMER_ROI.md).
    # recovery_benchmark.py is a separate pipeline step run after S9 - read
    # its outputs rather than recomputing the golden-year guards here.
    golden = pd.read_parquet("data/recovery_benchmark.parquet").set_index("site")
    with open("data/recovery_benchmark_meta.json") as f:
        rb_meta = json.load(f)

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
        # RECOVERY_BENCHMARK_AND_CUSTOMER_ROI.md §2.4: this warranty_active
        # feeds RVM eligibility ("not warranty_active"), not the reliability
        # warranty-valuation math in S14 - but it was using the blanket 25yr
        # module_performance term, which config.py's own comment says marks
        # ~all sites "in warranty" for every fault type. That collapsed RVM
        # eligibility to a single site fleet-wide. S14 already solved this
        # correctly for reliability failures with RELIABILITY_WARRANTY_YEARS
        # (blended inverter/module_product term, ~11yr) - use the same fix
        # here rather than reinventing it.
        warranty_active = bool(age_years is not None and age_years < config.RELIABILITY_WARRANTY_YEARS)
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

        # Part 1: the golden-year target and its guard flags - P50/P75 are
        # fleet-wide constants (payload meta, below), so only the per-site
        # "Proven" ingredients need to travel with each site.
        gy = golden.loc[site] if site in golden.index else None
        golden_out = dict(
            golden_available=bool(gy["golden_available"]) if gy is not None else False,
            golden_reason=gy["golden_reason"] if gy is not None else "not_computed",
            golden_year=ri(gy["golden_year"]) if gy is not None and pd.notna(gy["golden_year"]) else None,
            pri_golden_raw=r(gy["pri_golden_raw"], 4) if gy is not None and pd.notna(gy["pri_golden_raw"]) else None,
            pri_golden_floored=r(gy["pri_golden_floored"], 4) if gy is not None and pd.notna(gy["pri_golden_floored"]) else None,
            pri_golden_capped_flag=bool(gy["pri_golden_capped_flag"]) if gy is not None else False,
            pi_golden_floored=r(gy["pi_golden_floored"], 4) if gy is not None and pd.notna(gy["pi_golden_floored"]) else None,
            degradation_rate_annual=r(gy["degradation_rate_annual"], 4) if gy is not None else None,
            already_at_best=bool(gy["already_at_best"]) if gy is not None else False,
            capacity_suspect=bool(gy["capacity_suspect"]) if gy is not None else False,
        )

        site_payloads.append(dict(
            **routing, **roi, **golden_out,
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
            rel=reliability_site_lookup.get(site),
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
            scope=describe_scope(sites),
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
            # Part 1.4: the active benchmark must be stamped on every export
            # and printed page - the client reads this for the guard
            # thresholds/labels rather than hardcoding them a second time.
            recovery_benchmark=dict(
                default=config.RECOVERY_BENCHMARK_DEFAULT,
                percentiles=rb_meta["percentiles"],
                golden_min_months_in_year=config.GOLDEN_MIN_MONTHS_IN_YEAR,
                golden_min_years_history=config.GOLDEN_MIN_YEARS_HISTORY,
                golden_cap_pri=config.GOLDEN_CAP_PRI,
                golden_floor_at=config.GOLDEN_FLOOR_AT,
            ),
            customer_roi=dict(
                horizon_years=pricing["horizon_years"], discount_rate=pricing["discount_rate"],
                conversion=pricing["conversion"]["detection_to_remediation"],
                rvm_framing_default=config.CUSTOMER_ROI_RVM_FRAMING_DEFAULT,
                include_repair_spend=config.CUSTOMER_ROI_INCLUDE_REPAIR_SPEND,
                ratio_suppression_threshold=pricing["ratio_suppression_threshold"],
            ),
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
            # p50/p75 come from recovery_benchmark_meta.json (recovery_benchmark.py,
            # the same function s9_dollars.py now calls) rather than being
            # recomputed here a third way - test 86 needs these to match
            # S9's own PRI_P75/PI_P75 exactly, not just approximately.
            pi_p50=r(rb_meta["percentiles"]["pi_p50"], 3),
            pi_p75=r(rb_meta["percentiles"]["pi_p75"], 3),
            pri_p25=r(np.percentile(all_pri, 25), 3) if all_pri else None,
            pri_p50=r(rb_meta["percentiles"]["pri_p50"], 3),
            pri_p75=r(rb_meta["percentiles"]["pri_p75"], 3),
        ),
        signature_counts=sig_counts,
        year_signature_counts=year_sig_counts,
        hazard=hazard_out,
        sites=site_payloads,
        ledger=ledger_out,
        reliability=load_reliability(),
    )
    return payload


RELIABILITY_SIGS_SORTED = sorted(config.RELIABILITY_SIGNATURES)


def load_reliability(path: str = "data/reliability_fits.json") -> dict:
    """S12-S16 output (Reliability Engineering Addendum). Returns a minimal
    'not_available' shape if S12/S13 haven't been run this cycle, so the
    explorer degrades gracefully rather than crashing on a missing file.
    S14-S16 fleet-level aggregates (lost-energy bar, bathtub hazard-by-age,
    vintage scorecard, availability benchmark, owner spares rollup) are
    included when their files exist; per-site forecast/inspection/warranty
    data is returned separately by load_reliability_site_lookup() below,
    since it's the expensive part of the 25MB payload budget."""
    if not os.path.exists(path):
        log.warning("%s not found - Reliability panel will show 'not available' (run "
                    "s12_lifedata.py + s13_reliability.py first)", path)
        return dict(available=False, signatures=[], mttr_diagnostic=[])
    with open(path) as f:
        fits = json.load(f)
    signatures = []
    for s in fits["signatures"]:
        signatures.append(dict(
            signature=s["signature"],
            n_failures=s["n_failures"], n_suspensions=s["n_suspensions"],
            n_equipment_keys=s["n_equipment_keys"],
            below_min_failures_threshold=s["below_min_failures_threshold"],
            best_fit_family=s["best_fit"]["family"],
            best_fit_loglik=r(s["best_fit"]["loglik"], 1),
            weibull_beta=r(s["weibull_beta"], 3),
            weibull_eta_years=r(s["weibull_eta_years"], 2),
            beta_classification=s["beta_classification"],
            rvm_eligible=s["rvm_eligible"],
            all_fits=[dict(family=f["family"], loglik=r(f["loglik"], 1), aic=r(f["aic"], 1))
                      for f in s["all_fits"]],
        ))

    out = dict(
        available=True,
        generated_from=fits.get("generated_from"),
        signatures=signatures,
        mttr_diagnostic=[
            dict(signature=m["signature"], mttr_months=r(m["mttr_months"], 2),
                 median_months=r(m["median_months"], 1), n=m["n"])
            for m in fits.get("mttr_diagnostic", [])
        ],
        notes=[
            "beta > 1 (wear-out) is the ONLY classification eligible for "
            "preventive-replacement/RVM framing - beta < 1 (infant mortality) is a "
            "warranty conversation, never a 'replace before it breaks' one.",
            "SOILING's mean episode duration (MTTR) runs well above the addendum's "
            "~1.0 month reference - flagged as a signature-attribution question, "
            "not yet resolved. Treat SOILING-driven spares/forecast output as "
            "provisional until investigated.",
            "Forecasting/inspection/spares math (S14-S16) uses one fleet-wide "
            "Weibull fit per signature - there is no per-site or per-stratum refit "
            "in this pass, so every site's forecast leans on the same pooled prior.",
        ],
        lost_energy_by_signature=[], hazard_by_age=[], vintage_scorecard=[],
        availability_benchmark=None, bathtub_inflections={}, spares_by_owner={},
    )

    if os.path.exists("data/event_ledger.parquet"):
        ledger = pd.read_parquet("data/event_ledger.parquet")
        led = ledger[ledger["signature"].isin(config.RELIABILITY_SIGNATURES)]
        total = led["usd_lost"].sum()
        out["lost_energy_by_signature"] = [
            dict(signature=sig, lost_mwh=r(g["mwh_lost"].sum(), 0), lost_usd=r(g["usd_lost"].sum(), 0),
                 share_pct=r(100 * g["usd_lost"].sum() / total, 1) if total else 0)
            for sig, g in led.groupby("signature")
        ]

    if os.path.exists("data/hazard_by_age.parquet"):
        hazard = pd.read_parquet("data/hazard_by_age.parquet")
        out["hazard_by_age"] = [
            dict(signature=row["signature"], age_low=r(row["age_band_low"], 0), age_high=r(row["age_band_high"], 0),
                 hazard_rate=r(row["hazard_rate"], 4) if pd.notna(row["hazard_rate"]) else None,
                 exposure_years=r(row["exposure_years"], 1), n_sites=ri(row["n_sites"]))
            for _, row in hazard.iterrows()
        ]

    if os.path.exists("data/bathtub_inflections.json"):
        with open("data/bathtub_inflections.json") as f:
            out["bathtub_inflections"] = json.load(f)

    if os.path.exists("data/life_records.parquet") and os.path.exists("data/subsample_sites.parquet"):
        life = pd.read_parquet("data/life_records.parquet")
        sites_min = pd.read_parquet("data/subsample_sites.parquet")[["site", "tracking"]]
        life2 = life.merge(sites_min, on="site", how="left")
        life2["cod_band"] = life2["cod"].dt.year.map(
            lambda y: f"{(int(y)//3)*3}-{(int(y)//3)*3+2}" if pd.notna(y) else "unknown")
        vg = life2.groupby(["cod_band", "tracking"]).agg(
            sites=("site", "nunique"), failures=("status", lambda s: (s == "F").sum()),
            exposure_years=("duration_years", "sum")).reset_index()
        out["vintage_scorecard"] = [
            dict(cod_band=row["cod_band"], tracking=row["tracking"], sites=ri(row["sites"]),
                 failures=ri(row["failures"]), exposure_years=r(row["exposure_years"], 1),
                 lambda_site_yr=r(row["failures"] / row["exposure_years"], 3) if row["exposure_years"] else None)
            for _, row in vg.iterrows()
        ]

    if os.path.exists("data/site_month_dollars.parquet"):
        smd = pd.read_parquet("data/site_month_dollars.parquet")
        site_target = smd.groupby("site")["T_mwh"].sum()
        site_act = smd.groupby("site")["E_act_mwh"].sum()
        avail = (1 - (site_target - site_act).clip(lower=0) / site_target.replace(0, float("nan"))).dropna()
        if len(avail):
            out["availability_benchmark"] = dict(
                median=r(avail.median(), 4), p10=r(avail.quantile(0.10), 4), p90=r(avail.quantile(0.90), 4))

    if os.path.exists("data/spares_plan.parquet"):
        spares = pd.read_parquet("data/spares_plan.parquet")
        out["spares_by_owner"] = {
            row["owner"]: dict(n_sites=ri(row["n_sites"]), blocks_at_risk=ri(row["blocks_at_risk"]),
                                expected_block_failures_24mo=r(row["expected_block_failures_24mo"], 2),
                                spares_needed_95pct=ri(row["spares_needed_95pct"]),
                                gap_at_0_held=ri(row["spares_needed_95pct"]))
            for _, row in spares.iterrows()
        }

    return out


def load_reliability_site_lookup() -> dict:
    """Per-site reliability fields (S14/S16), keyed by site name, in the
    same fixed 6-signature order as RELIABILITY_SIGS_SORTED so per-site
    entries don't repeat signature name strings - this is the expensive
    part of the payload addition (addendum Section 10's own budget
    warning), kept to parallel arrays of rounded numbers accordingly."""
    if not (os.path.exists("data/reliability_forecast.parquet") and os.path.exists("data/life_records.parquet")):
        return {}

    life = pd.read_parquet("data/life_records.parquet")
    last = life.sort_values("spell_index").groupby(["site", "signature"], as_index=False).tail(1)
    forecast = pd.read_parquet("data/reliability_forecast.parquet")
    inspection = pd.read_parquet("data/inspection_schedule.parquet") if os.path.exists("data/inspection_schedule.parquet") else None
    warranty = pd.read_parquet("data/warranty_valuation.parquet") if os.path.exists("data/warranty_valuation.parquet") else None

    lookup = {}
    n_blocks_by_site = last.groupby("site")["n_blocks"].first()
    age_by_site = last.groupby("site")["age_last_known_years"].max()
    fc_grouped = forecast.groupby(["site", "signature"]) if len(forecast) else None

    for site in age_by_site.index:
        entry = dict(nb=ri(n_blocks_by_site.get(site)), age=r(age_by_site.get(site), 2),
                     at_risk=[], p12=[], p24=[], p36=[])
        for sig in RELIABILITY_SIGS_SORTED:
            key = (site, sig)
            if fc_grouped is not None and key in fc_grouped.groups:
                rows = forecast.loc[fc_grouped.groups[key]].set_index("horizon_months")
                entry["at_risk"].append(True)
                entry["p12"].append(r(rows.loc[12, "cond_prob_failure"], 4) if 12 in rows.index else None)
                entry["p24"].append(r(rows.loc[24, "cond_prob_failure"], 4) if 24 in rows.index else None)
                entry["p36"].append(r(rows.loc[36, "cond_prob_failure"], 4) if 36 in rows.index else None)
            else:
                entry["at_risk"].append(False)
                entry["p12"].append(None); entry["p24"].append(None); entry["p36"].append(None)
        lookup[site] = entry

    if inspection is not None:
        for row in inspection.itertuples():
            if row.site in lookup:
                lookup[row.site]["insp"] = [ri(row.optimal_interval_months), r(row.optimal_total_cost_usd, 0),
                                             r(row.saving_vs_current_usd, 0), r(row.scada_value_usd, 0)]

    if warranty is not None:
        for row in warranty.itertuples():
            if row.site in lookup:
                lookup[row.site]["war"] = [r(row.remaining_window_years, 2), r(row.claim_value_usd, 0)]

    return lookup


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


def write_roi_export(site_payloads: list) -> None:
    """RECOVERY_BENCHMARK_AND_CUSTOMER_ROI.md - repair cost, RVM fees and
    customer-ROI are all computed here, once, per §6's own recurring
    caution (the cockpit's site view should read the same functions, not
    reimplement them). ceo_cockpit reads this rather than recomputing."""
    cols = ["site", "repair_cost_usd", "repair_uneconomic", "rvm_fee_gross_usd", "rvm_fee_incremental_usd",
            "rvm_eligible", "customer_roi_benefit_usd", "customer_roi_ssi_fees_usd",
            "customer_roi_repair_outlay_usd", "customer_roi_cost_usd", "customer_roi_net_benefit_usd",
            "customer_roi_multiple", "customer_roi_payback_months", "customer_roi_irr",
            "customer_roi_excluded", "golden_available", "golden_year", "pri_golden_raw",
            "pri_golden_floored", "pri_golden_capped_flag", "pi_golden_floored",
            "degradation_rate_annual", "already_at_best", "capacity_suspect"]
    rows = [{c: s.get(c) for c in cols} for s in site_payloads]
    pd.DataFrame(rows).to_parquet("data/site_roi_export.parquet", index=False)
    log.info("wrote data/site_roi_export.parquet: %d sites", len(rows))


def main():
    payload = build_payload()
    write_roi_export(payload["sites"])
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
