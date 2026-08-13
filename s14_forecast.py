"""
S14 - Forecasting (Reliability Engineering Addendum, Section 6), plus the
bathtub-curve hazard-by-age table (Section 3/9.8, feeds the Fleet
Reliability tab and the workbook's Hazard by Age tab) and warranty
valuation (Section 9.2).

Forecasting uses the fleet-level Weibull fit per signature (data/
reliability_fits.json) - the addendum's own stratification is deferred
(min_failures_to_fit=20 is tight once split by tracking/vintage/tech, and
"beta is the whole point" throughout Sections 3, 5 and 6 all center the
Weibull parameterization specifically, even where a different family wins
the AIC race). Every site therefore shares the same beta/eta prior; there
is no per-site refit, so credibility_Z here measures how much of a site's
own history is behind its current state, not a per-site vs pooled blend.

Only equipment_keys currently NOT mid-episode are at risk (Section 6's
"a site already in a running episode of that signature is not at risk of
starting one" rule) - S12 already encodes this: a life record whose last
spell is status='S' has a real t0; one whose last spell is 'F' with no
tail suspension is still inside the fault and is excluded here.
"""
import json
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S14 %(message)s")
log = logging.getLogger("s14")

from s11_explorer import repair_cost, load_pricing  # noqa: E402 - after basicConfig so S14's own log format wins


def weibull_R(t, beta, eta):
    t = np.maximum(t, 0)
    return np.exp(-((t / eta) ** beta))


def current_state(life: pd.DataFrame) -> pd.DataFrame:
    """One row per equipment_key: its current t0 (age_last_known_years) and
    whether it's at risk (last spell right-censored, not an open fault)."""
    last = life.sort_values("spell_index").groupby("equipment_key", as_index=False).tail(1)
    last["at_risk"] = last["status"] == "S"
    return last


def credibility_z(entry_age, current_age, ref_years=5.0):
    """Illustrative shrinkage weight: how much of a site's OWN observed
    history backs its forecast, given every site shares one fleet-level
    Weibull fit (no per-site or per-stratum refit in this pass). NOT a
    formal empirical-Bayes credibility estimator - flagged as such
    wherever it's surfaced."""
    observed_years = max(0.0, current_age - entry_age)
    return float(min(1.0, observed_years / ref_years))


def build_forecast(life: pd.DataFrame, fits: dict) -> pd.DataFrame:
    beta_eta = {s["signature"]: (s["weibull_beta"], s["weibull_eta_years"]) for s in fits["signatures"]}
    cur = current_state(life)
    at_risk = cur[cur["at_risk"]].copy()
    log.info("%d/%d equipment_keys at risk (%d currently mid-episode, excluded)",
              len(at_risk), len(cur), (~cur["at_risk"]).sum())

    rows = []
    for row in at_risk.itertuples():
        beta, eta = beta_eta[row.signature]
        t0 = row.age_last_known_years
        R_now = weibull_R(t0, beta, eta)
        z = credibility_z(row.age_entry_years, t0)
        for h in config.RELIABILITY["forecast_horizons_months"]:
            t_future = t0 + h / 12.0
            R_future = weibull_R(t_future, beta, eta)
            cond_prob = 1.0 - (R_future / R_now if R_now > 0 else 1.0)
            cond_prob = float(np.clip(cond_prob, 0.0, 1.0))
            rows.append(dict(
                site=row.site, signature=row.signature, n_blocks=row.n_blocks,
                age_years=round(t0, 3), horizon_months=h,
                R_now=round(float(R_now), 6), R_future=round(float(R_future), 6),
                cond_prob_failure=round(cond_prob, 6),
                expected_failures=round(cond_prob, 6),
                expected_failures_block_level=round(cond_prob * row.n_blocks, 4),
                beta=round(beta, 4), eta=round(eta, 4), distribution="weibull",
                loglik=None, stratum="fleet", credibility_Z=round(z, 3),
                left_truncated=True,
            ))
    out = pd.DataFrame(rows)
    bad = out[(out["cond_prob_failure"] < 0) | (out["cond_prob_failure"] > 1)]
    assert len(bad) == 0, f"{len(bad)} forecast rows outside [0,1] (test 41)"
    for sig in out["signature"].unique():
        sub = out[out["signature"] == sig].sort_values("horizon_months")
        for site, g in sub.groupby("site"):
            probs = g.sort_values("horizon_months")["cond_prob_failure"].to_numpy()
            assert np.all(np.diff(probs) >= -1e-9), f"non-monotonic forecast at {site}/{sig} (test 41)"
    return out


def build_hazard_by_age(life: pd.DataFrame, band_width: float = 2.0, max_age: float = 26.0) -> pd.DataFrame:
    """Bathtub-curve input: empirical hazard (failures / exposure-years) by
    age band per signature. Each life record's exposure is attributed to
    the age band containing its interval midpoint."""
    bands = np.arange(0, max_age + band_width, band_width)
    life = life.copy()
    mid_age = (life["age_entry_years"].fillna(life["age_at_event_years"]) + life["age_at_event_years"]) / 2
    life["age_band_idx"] = np.clip(np.digitize(mid_age, bands) - 1, 0, len(bands) - 2)
    life["age_band_low"] = bands[life["age_band_idx"]]
    life["age_band_high"] = life["age_band_low"] + band_width
    life["is_failure"] = life["status"] == "F"

    out = (life.groupby(["signature", "age_band_low", "age_band_high"])
           .agg(failures=("is_failure", "sum"), exposure_years=("duration_years", "sum"),
                n_sites=("site", "nunique"))
           .reset_index())
    out["hazard_rate"] = np.where(out["exposure_years"] > 0, out["failures"] / out["exposure_years"], np.nan)
    return out.sort_values(["signature", "age_band_low"])


def find_bathtub_inflections(hazard: pd.DataFrame) -> dict:
    """Very simple inflection finder: for each signature, the age band
    where hazard rate stops falling (end of infant mortality) and where it
    starts rising again (start of wear-out), using only bands with >=3
    site-years of exposure to avoid reading noise as a trend. Exploratory
    per the addendum (Section 9.8) - not asserted against a reference."""
    result = {}
    for sig, g in hazard.groupby("signature"):
        g = g[g["exposure_years"] >= 3].sort_values("age_band_low")
        if len(g) < 3:
            result[sig] = dict(infant_end_years=None, wearout_start_years=None, note="insufficient exposure")
            continue
        rates = g["hazard_rate"].to_numpy()
        ages = g["age_band_low"].to_numpy()
        infant_end = None
        for i in range(1, len(rates)):
            if rates[i] >= rates[i - 1]:
                infant_end = float(ages[i])
                break
        wearout_start = None
        if infant_end is not None:
            for i in range(len(rates) - 1, 0, -1):
                if rates[i] < rates[i - 1]:
                    continue
                wearout_start = float(ages[i])
        result[sig] = dict(infant_end_years=infant_end, wearout_start_years=wearout_start, note=None)
    return result


def build_warranty_valuation(life: pd.DataFrame, sites: pd.DataFrame, episodes: pd.DataFrame,
                              fits: dict, pricing: dict) -> pd.DataFrame:
    """Section 9.2, with the warranty-gate fix from Section 9.2's own
    closing note: uses config.RELIABILITY_WARRANTY_YEARS (blended
    inverter/module-product term), NOT the 25yr module_performance term
    that marks nearly the whole fleet as in-warranty."""
    beta_eta = {s["signature"]: (s["weibull_beta"], s["weibull_eta_years"]) for s in fits["signatures"]}
    severity = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)].groupby("signature")["max_D"].mean()

    cur = current_state(life)
    at_risk = cur[cur["at_risk"]].copy()
    site_meta = sites.set_index("site")[["cod", "mwdc"]]

    rows = []
    for site, g in at_risk.groupby("site"):
        cod = site_meta.loc[site, "cod"]
        mwdc = site_meta.loc[site, "mwdc"]
        age_now = g["age_last_known_years"].iloc[0]
        remaining = config.RELIABILITY_WARRANTY_YEARS - age_now
        if remaining <= 0:
            continue
        expected_failures = 0.0
        claim_value = 0.0
        for row in g.itertuples():
            beta, eta = beta_eta[row.signature]
            t0 = row.age_last_known_years
            R_now = weibull_R(t0, beta, eta)
            R_future = weibull_R(t0 + remaining, beta, eta)
            q = float(np.clip(1.0 - (R_future / R_now if R_now > 0 else 1.0), 0.0, 1.0))
            expected_failures += q
            sev = severity.get(row.signature, 0.15)
            rc = repair_cost(row.signature, sev, mwdc, pricing)
            claim_value += q * (rc["repair_cost_usd"] or 0)
        rows.append(dict(
            site=site, cod=cod, age_years=round(age_now, 3),
            warranty_years=config.RELIABILITY_WARRANTY_YEARS, remaining_window_years=round(remaining, 3),
            expected_failures_in_warranty=round(expected_failures, 4),
            claim_value_usd=round(claim_value, 0), mwdc=mwdc,
        ))
    return pd.DataFrame(rows)


def main():
    life = pd.read_parquet("data/life_records.parquet")
    sites = pd.read_parquet("data/subsample_sites.parquet")
    episodes = pd.read_parquet("data/episodes.parquet")
    with open("data/reliability_fits.json") as f:
        fits = json.load(f)
    pricing = load_pricing()

    forecast = build_forecast(life, fits)
    forecast.to_parquet("data/reliability_forecast.parquet", index=False)
    log.info("forecast: %d rows (%d sites x %d signatures x %d horizons) -> "
              "data/reliability_forecast.parquet", len(forecast), forecast["site"].nunique(),
              forecast["signature"].nunique(), len(config.RELIABILITY["forecast_horizons_months"]))

    hazard = build_hazard_by_age(life)
    hazard.to_parquet("data/hazard_by_age.parquet", index=False)
    inflections = find_bathtub_inflections(hazard)
    log.info("hazard-by-age: %d (signature, age-band) cells -> data/hazard_by_age.parquet", len(hazard))
    for sig, inf in inflections.items():
        log.info("  %-18s infant_end=%s  wearout_start=%s  %s", sig, inf["infant_end_years"],
                  inf["wearout_start_years"], inf["note"] or "")
    with open("data/bathtub_inflections.json", "w") as f:
        json.dump(inflections, f, indent=2)

    warranty = build_warranty_valuation(life, sites, episodes, fits, pricing)
    warranty.to_parquet("data/warranty_valuation.parquet", index=False)
    ages = (current_state(life)[["site", "age_last_known_years"]].drop_duplicates("site"))
    n_old_gate = int((ages["age_last_known_years"] < config.WARRANTY_DEFAULTS_YEARS["module_performance"]).sum())
    log.info("warranty valuation: %d/%d sites still within the %.1fyr reliability warranty term "
              "(vs %d/%d the blanket 25yr module_performance term would have wrongly marked in-warranty) "
              "-> data/warranty_valuation.parquet, total claim value $%.0f",
              len(warranty), sites["site"].nunique(), config.RELIABILITY_WARRANTY_YEARS,
              n_old_gate, ages["site"].nunique(), warranty["claim_value_usd"].sum())

    log.info("S14 complete")


if __name__ == "__main__":
    main()
