"""
S8 - Event ledger + hazard/frailty + credibility + EAL (Part 7).

PER THE BRIEF'S OWN BUILD ORDER (Section 12): S8-S9 are meant to run AFTER
scaling up to the full 6,204-site fleet, not on the 100-site validation
subsample - "Then scale up, then S8-S9, then the explorer." This module is
built and smoke-tested against the subsample now so the code is ready, but
its hazard-shape, negative-binomial and credibility outputs are NOT
statistically meaningful at n~100 sites and should not be read as results.
Re-run at full scale before trusting lambda/EAL numbers.
"""
import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S8 %(message)s")
log = logging.getLogger("s8")


def month_ordinal(ts: pd.Timestamp) -> int:
    return ts.year * 12 + ts.month


def build_episodes(df: pd.DataFrame) -> pd.DataFrame:
    """Maximal runs of consecutive months (1-month gap tolerance) sharing the
    same signature_final, at the FAULT-ledger signatures only. A missing
    month neither breaks nor extends a run (it's simply absent from the
    per-site timeline, since production_gated never emits a row for it)."""
    episodes = []
    for site, g in df[df["fault_flag"]].groupby("site"):
        g = g.sort_values("month_start")
        for sig, sg in g.groupby("signature_final"):
            sg = sg.sort_values("month_start").reset_index(drop=True)
            run_start = sg.iloc[0]
            prev = run_start
            run_months = [run_start]
            for i in range(1, len(sg)):
                row = sg.iloc[i]
                if month_ordinal(row["month_start"]) - month_ordinal(prev["month_start"]) <= config.EPISODE_GAP_TOLERANCE_MONTHS + 1:
                    run_months.append(row)
                else:
                    episodes.append(dict(site=site, signature=sig,
                                          start=run_months[0]["month_start"],
                                          end=run_months[-1]["month_start"],
                                          n_months=len(run_months),
                                          max_D=max(r["D"] for r in run_months)))
                    run_months = [row]
                prev = row
            episodes.append(dict(site=site, signature=sig,
                                  start=run_months[0]["month_start"],
                                  end=run_months[-1]["month_start"],
                                  n_months=len(run_months),
                                  max_D=max(r["D"] for r in run_months)))
    return pd.DataFrame(episodes)


def build_ledger(df: pd.DataFrame, episodes: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    cod = sites.set_index("site")["cod"]
    rows = []
    for (site, year), g in df.groupby(["site", "year"]):
        exposure_months = g["scoreable_months_in_year"].iloc[0] if "scoreable_months_in_year" in g else g["D"].notna().sum()
        age_start = ((pd.Timestamp(f"{year}-01-01") - cod.get(site, pd.NaT)).days / 365.25
                     if pd.notna(cod.get(site, pd.NaT)) else np.nan)
        for sig in config.FAULT_LEDGER_SIGNATURES | config.EXPOSURE_LEDGER_SIGNATURES | config.STATE_LEDGER_SIGNATURES:
            months = (g["signature_final"] == sig).sum()
            if months == 0:
                continue
            ep = episodes[(episodes["site"] == site) & (episodes["signature"] == sig) &
                          (episodes["start"].dt.year <= year) & (episodes["end"].dt.year >= year)]
            n_episodes = len(ep) if sig in config.FAULT_LEDGER_SIGNATURES else np.nan
            mwh_lost = g.loc[g["signature_final"] == sig, "gross_gap_mwh"].sum() if "gross_gap_mwh" in g else np.nan
            usd_lost = g.loc[g["signature_final"] == sig, "value_usd"].sum() if "value_usd" in g else np.nan
            max_sev = g.loc[g["signature_final"] == sig, "D"].max()
            rows.append(dict(site=site, year=year, signature=sig, months=months,
                              episodes=n_episodes, exposure_months=exposure_months,
                              age_start=age_start, mwh_lost=mwh_lost, usd_lost=usd_lost,
                              max_severity=max_sev))
    return pd.DataFrame(rows)


def hazard_by_age_band(ledger: pd.DataFrame) -> pd.DataFrame:
    """Lightweight hazard-shape diagnostic: episodes per exposure-year by age
    band and signature. A full Weibull MLE needs far more data than the
    100-site subsample provides; this bucketed rate is the qualitative
    substitute (rising/flat/falling with age) called for by acceptance
    test 23, with the MLE fit reserved for the full-scale run."""
    fault = ledger[ledger["signature"].isin(config.FAULT_LEDGER_SIGNATURES) & ledger["episodes"].notna()].copy()
    fault["age_band"] = pd.cut(fault["age_start"], bins=[0, 2, 4, 6, 8, 12, 100],
                                labels=["0-2", "2-4", "4-6", "6-8", "8-12", "12+"])
    agg = fault.groupby(["signature", "age_band"], observed=True).agg(
        episodes=("episodes", "sum"), exposure_years=("exposure_months", lambda s: s.sum() / 12)
    ).reset_index()
    agg["rate_per_exposure_year"] = agg["episodes"] / agg["exposure_years"].replace(0, np.nan)
    return agg


def fit_negbin_rate_model(ledger: pd.DataFrame, sites: pd.DataFrame) -> dict:
    """One negative-binomial GLM per fault signature: log E[K] = offset(log
    exposure_years) + covariates. Reports Var/mean (test 12) regardless of
    whether the GLM converges - that check doesn't need the model."""
    fault = ledger[ledger["signature"].isin(config.FAULT_LEDGER_SIGNATURES) & ledger["episodes"].notna()].copy()
    meta = sites.set_index("site")[["tracking", "dcac", "mwac", "state"]]
    fault = fault.merge(meta, left_on="site", right_index=True, how="left")
    fault = fault[fault["exposure_months"] > 0]
    fault["exposure_years"] = fault["exposure_months"] / 12.0

    results = {}
    for sig, g in fault.groupby("signature"):
        var_mean = g["episodes"].var() / g["episodes"].mean() if g["episodes"].mean() > 0 else np.nan
        entry = dict(n_site_years=len(g), var_over_mean=var_mean, converged=False)
        if len(g) >= 30 and g["episodes"].sum() >= 10:
            try:
                gg = g.copy()
                gg["log_exposure"] = np.log(gg["exposure_years"].clip(lower=1 / 12))
                model = smf.glm(
                    "episodes ~ C(tracking) + dcac", data=gg,
                    family=sm.families.NegativeBinomial(),
                    offset=gg["log_exposure"],
                ).fit()
                entry["converged"] = True
                entry["alpha_intercept"] = model.params.get("Intercept", np.nan)
                entry["aic"] = model.aic
            except Exception as e:
                entry["fit_error"] = str(e)
        else:
            entry["fit_error"] = f"too sparse at subsample scale (n={len(g)} site-years, {g['episodes'].sum()} episodes)"
        results[sig] = entry
    return results


def credibility_shrinkage(ledger: pd.DataFrame) -> pd.DataFrame:
    """Empirical-Bayes-style shrinkage toward the fleet pooled rate.
    tau_s estimated from the (site-level) variance decomposition where
    feasible; falls back to a documented prior (tau_s = pooled mean) when
    a site has too few years to estimate Var(K|i) - expected at subsample
    scale."""
    fault = ledger[ledger["signature"].isin(config.FAULT_LEDGER_SIGNATURES) & ledger["episodes"].notna()].copy()
    fault = fault[fault["exposure_months"] > 0]
    out = []
    for sig, g in fault.groupby("signature"):
        pooled_rate = g["episodes"].sum() / (g["exposure_months"].sum() / 12)
        by_site = g.groupby("site").agg(K=("episodes", "sum"), E=("exposure_months", lambda s: s.sum() / 12))
        var_between = by_site["K"].var() if len(by_site) > 3 else np.nan
        tau_s = pooled_rate if pd.isna(var_between) or var_between <= 0 else max(pooled_rate, var_between)
        for site, row in by_site.iterrows():
            Z = row["E"] / (row["E"] + tau_s) if (row["E"] + tau_s) > 0 else 0
            lam = Z * (row["K"] / row["E"]) + (1 - Z) * pooled_rate if row["E"] > 0 else pooled_rate
            out.append(dict(site=site, signature=sig, lambda_shrunk=lam, credibility_Z=Z,
                             pool_level="fleet_age_adjusted_subsample", tau_s=tau_s))
    return pd.DataFrame(out)


def main():
    df = pd.read_parquet("data/site_month_signatures.parquet")
    sites = pd.read_parquet("data/sites_gated.parquet")

    episodes = build_episodes(df)
    episodes.to_parquet("data/episodes.parquet", index=False)

    ledger = build_ledger(df, episodes, sites)
    ledger.to_parquet("data/event_ledger.parquet", index=False)

    hazard = hazard_by_age_band(ledger)
    hazard.to_parquet("data/hazard_by_age_band.parquet", index=False)

    negbin = fit_negbin_rate_model(ledger, sites)
    credibility = credibility_shrinkage(ledger)
    credibility.to_parquet("data/credibility.parquet", index=False)

    log.info("S8 complete: %d episodes, %d ledger rows", len(episodes), len(ledger))
    log.info("Var/mean by signature (test 12): %s",
              {k: round(v["var_over_mean"], 2) if pd.notna(v["var_over_mean"]) else None
               for k, v in negbin.items()})
    for sig, r in negbin.items():
        log.info("  %s: n_site_years=%d, converged=%s%s", sig, r["n_site_years"], r["converged"],
                  f", note={r.get('fit_error')}" if not r["converged"] else "")
    import json
    with open("data/negbin_summary.json", "w") as f:
        json.dump({k: {kk: (vv if not isinstance(vv, (np.floating, np.integer)) else float(vv))
                        for kk, vv in v.items()} for k, v in negbin.items()}, f, indent=2, default=str)


if __name__ == "__main__":
    main()
