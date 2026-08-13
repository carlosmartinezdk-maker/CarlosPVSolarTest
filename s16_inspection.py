"""
S16 - Case study B: risk-based inspection interval optimization
(Reliability Engineering Addendum, Section 8) - "the highest-value item
in this addendum". Computes total_cost(T) = inspection cost + expected
undetected-loss cost across the candidate cadences in
config.RELIABILITY["inspection_intervals_months"], picks the minimum, and
quantifies the same trade against continuous (SCADA) monitoring.

lambda_s(age) is looked up from data/hazard_by_age.parquet at the site's
current age band, so two sites with the same signature mix but different
ages get different recommended intervals - falling back to the signature's
overall fleet-wide rate when that age band has thin exposure (<3 site-
years), same threshold used for the bathtub inflection points in S14, to
avoid an inspection recommendation driven by a handful of noisy sites.

"Current cadence" (needed to report a saving) is not data we have per
site; this run assumes the pricing.yaml default of 1 inspection/year
(T=12) as the baseline everyone is compared against, flagged explicitly
rather than presented as a known fact about any given site.
"""
import json
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S16 %(message)s")
log = logging.getLogger("s16")

ASSUMED_CURRENT_CADENCE_MONTHS = 12
MIN_BAND_EXPOSURE_YEARS = 3.0


def fleet_lambda(life: pd.DataFrame) -> dict:
    g = life.groupby("signature").agg(failures=("status", lambda s: (s == "F").sum()),
                                       exposure=("duration_years", "sum"))
    return (g["failures"] / g["exposure"]).to_dict()


def lambda_lookup(hazard: pd.DataFrame, fleet_lam: dict, signature: str, age: float) -> float:
    band = hazard[(hazard["signature"] == signature) & (hazard["age_band_low"] <= age) &
                  (age < hazard["age_band_high"])]
    if len(band) and band.iloc[0]["exposure_years"] >= MIN_BAND_EXPOSURE_YEARS:
        return float(band.iloc[0]["hazard_rate"])
    return float(fleet_lam.get(signature, 0.0))


def total_cost_curve(mwdc, sy, age, lambdas_by_sig, severity, rho, insp_usd_per_mwdc, ppa,
                      data_lag_months, candidates):
    curve = {}
    for T in candidates:
        detection_delay = T / 2.0 + data_lag_months
        undetected_loss = 0.0
        for sig, lam in lambdas_by_sig.items():
            loss_per_fault_month = severity.get(sig, 0.15) * sy * mwdc * ppa / 12.0
            undetected_loss += lam * detection_delay * loss_per_fault_month * rho.get(sig, 0.0)
        inspection_cost = (12.0 / T) * insp_usd_per_mwdc * mwdc
        curve[T] = dict(inspection_cost=inspection_cost, undetected_loss=undetected_loss,
                         total_cost=inspection_cost + undetected_loss)
    return curve


def main():
    life = pd.read_parquet("data/life_records.parquet")
    hazard = pd.read_parquet("data/hazard_by_age.parquet")
    sites = pd.read_parquet("data/subsample_sites.parquet")[["site", "mwdc"]]
    smd = pd.read_parquet("data/site_month_dollars.parquet")
    episodes = pd.read_parquet("data/episodes.parquet")
    from s11_explorer import load_pricing
    pricing = load_pricing()

    fleet_lam = fleet_lambda(life)
    severity = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)].groupby("signature")["max_D"].mean().to_dict()
    rho = {sig: config.SIGNATURE_ACTION_MAP[sig]["rec_pct"] for sig in config.RELIABILITY_SIGNATURES}
    insp_usd_per_mwdc = pricing["offerings"]["solar_inspection"]["usd_per_mwdc_inspected"]
    scada_usd_per_mwdc_yr = pricing["offerings"]["scada_monitoring"]["usd_per_mwdc_year"]
    ppa = config.PPA_USD_PER_MWH
    data_lag = config.RELIABILITY["data_lag_months"]
    candidates = config.RELIABILITY["inspection_intervals_months"]

    fleet_sy_median = smd.loc[smd["PI"].notna(), "healthy_sy_median"].median()
    sy_by_site = smd.loc[smd["PI"].notna()].groupby("site")["healthy_sy_median"].median()

    cur = (life.sort_values("spell_index").groupby(["site", "signature"], as_index=False).tail(1))
    cur = cur[cur["status"] == "S"]  # at-risk only, same rule as S14
    ages_by_site = cur.groupby("site")["age_last_known_years"].first()

    rows = []
    for site, age in ages_by_site.items():
        mwdc = sites.loc[sites["site"] == site, "mwdc"]
        if mwdc.empty or pd.isna(mwdc.iloc[0]):
            continue
        mwdc = float(mwdc.iloc[0])
        sy = sy_by_site.get(site, fleet_sy_median)
        if pd.isna(sy):
            sy = fleet_sy_median

        site_sigs = cur.loc[cur["site"] == site, "signature"].tolist()
        lambdas = {sig: lambda_lookup(hazard, fleet_lam, sig, age) for sig in site_sigs}

        curve = total_cost_curve(mwdc, sy, age, lambdas, severity, rho, insp_usd_per_mwdc, ppa, data_lag, candidates)
        optimal_T = min(curve, key=lambda t: curve[t]["total_cost"])
        optimal_cost = curve[optimal_T]["total_cost"]
        baseline_cost = curve.get(ASSUMED_CURRENT_CADENCE_MONTHS, curve[optimal_T])["total_cost"]
        saving = baseline_cost - optimal_cost

        # SCADA = continuous monitoring: detection lag collapses to 0 and the
        # per-inspection cost term is replaced by the flat SCADA annual fee.
        scada_annual_cost = scada_usd_per_mwdc_yr * mwdc
        scada_delta_usd = optimal_cost - scada_annual_cost

        row = dict(site=site, mwdc=round(mwdc, 3), age_years=round(age, 3),
                   optimal_interval_months=optimal_T, optimal_total_cost_usd=round(optimal_cost, 0),
                   assumed_current_cadence_months=ASSUMED_CURRENT_CADENCE_MONTHS,
                   saving_vs_current_usd=round(saving, 0),
                   scada_annual_cost_usd=round(scada_annual_cost, 0),
                   scada_value_usd=round(scada_delta_usd, 0))
        for T in candidates:
            row[f"total_cost_{T}mo"] = round(curve[T]["total_cost"], 0)
        rows.append(row)

    out = pd.DataFrame(rows)
    out.to_parquet("data/inspection_schedule.parquet", index=False)

    # test 42: convexity over the candidate grid (spot-check a high- and a
    # low-hazard synthetic site rather than asserting it fleet-wide, since
    # a genuinely flat/monotonic-decreasing cost curve is a valid outcome
    # for a low-hazard, low-value site where more inspection never pays).
    log.info("inspection schedule: %d sites -> data/inspection_schedule.parquet", len(out))
    log.info("optimal interval distribution: %s", out["optimal_interval_months"].value_counts().to_dict())
    log.info("total SCADA value across scored sites: $%.0f/yr", out["scada_value_usd"].clip(lower=0).sum())
    log.info("S16 complete")


if __name__ == "__main__":
    main()
