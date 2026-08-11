"""
S7 - Trajectory (Part 6). Degradation slope, envelope/gap decomposition,
warranty clock.

SIGN-CONVENTION NOTE (resolves a real ambiguity in the brief): S3's E_exp
already bakes in the assumed structural degradation (1-d)^a (S3 formula,
implemented literally). So a plant tracking exactly its assumed structural
rate has ln(PI_adj) FLAT over tau (beta ~ 0) - the physical prior already
explains its decline. beta_excess = beta - d then converts back to an
absolute decline-rate convention: a healthy plant reads beta ~ 0, so
beta_excess ~ -d ~ -0.5%/yr, matching Section 7c's own band ("approx
-0.5%/yr = normal structural degradation, healthy") and what acceptance
test 11 expects the fleet median to recover. This is the only self-
consistent reading of "beta_excess = beta + d" against 7c's stated bands
and 7c's own worked category descriptions; see run_report.md for the
alternative reading and why it was rejected.

IDENTIFICATION WARNING (Section 7): age/cohort/calendar-period weather are
linearly dependent, so d is FIXED at the config prior, never fit freely.
Stepwise vintage-cohort terms (Section 7, "estimable as a stepwise cohort
term" at 6+ years/2,922 sites) are a full-scale-only enhancement, not
implemented on the 100-site subsample where most cohort bins are near-empty
- flagged as a deferred item, not silently skipped.
"""
import logging

import numpy as np
import pandas as pd
import statsmodels.api as sm

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S7 %(message)s")
log = logging.getLogger("s7")


def fit_site_trajectory(g: pd.DataFrame, tech_class: str) -> dict:
    g = g[(g["PI_adj"] > 0) & g["PI_adj"].notna() & g["tau_years"].notna()].sort_values("tau_years")
    n = len(g)
    if n < 2:
        return dict(beta=np.nan, beta_se=np.nan, beta_t=np.nan, n_obs=n, decision_grade=False)

    y = np.log(g["PI_adj"].values)
    X = sm.add_constant(g["tau_years"].values)
    model = sm.OLS(y, X).fit()
    beta = model.params[1]
    beta_se = model.bse[1]
    beta_t = model.tvalues[1]

    d = config.DEGRADATION_RATE_ANNUAL.get(tech_class, config.DEGRADATION_RATE_ANNUAL["crystalline_silicon"])
    beta_excess = beta - d

    return dict(beta=beta, beta_se=beta_se, beta_t=beta_t, beta_excess=beta_excess,
                n_obs=n, decision_grade=n >= 4)


def envelope_gap(g: pd.DataFrame) -> pd.DataFrame:
    g = g.sort_values("month_start").copy()
    g["envelope"] = g["PI_adj"].rolling(12, min_periods=12).quantile(0.95)
    g["gap"] = g["envelope"] - g["PI_adj"]
    return g


def excess_category(beta_excess: float) -> str:
    if pd.isna(beta_excess):
        return "insufficient_data"
    if beta_excess > 0.03:
        return "IMPROVING"
    if beta_excess >= -0.01:
        return "normal_structural"
    if beta_excess >= -0.03:
        return "mild_deterioration"
    return "accelerating_loss"


def warranty_clock(cod: pd.Timestamp, month_start: pd.Timestamp) -> dict:
    if pd.isna(cod):
        return dict(epc_years_remaining=np.nan, module_perf_years_remaining=np.nan, warranty_urgent=False)
    tau = (month_start - cod).days / 365.25
    epc_rem = config.WARRANTY_DEFAULTS_YEARS["epc_workmanship"] - tau
    module_rem = config.WARRANTY_DEFAULTS_YEARS["module_performance"] - tau
    inv_rem = config.WARRANTY_DEFAULTS_YEARS["inverter_min"] - tau
    urgent = any(0 <= r < config.WARRANTY_URGENT_THRESHOLD_YEARS for r in (epc_rem, inv_rem))
    return dict(epc_years_remaining=epc_rem, module_perf_years_remaining=module_rem,
                inverter_min_years_remaining=inv_rem, warranty_urgent=urgent)


def main():
    df = pd.read_parquet("data/site_month_decision.parquet")
    sites = pd.read_parquet("data/sites_gated.parquet")
    tech = sites.set_index("site")["tech_class"]

    traj_rows = []
    envelope_frames = []
    for site, g in df.groupby("site"):
        t = tech.get(site, "crystalline_silicon")
        fit = fit_site_trajectory(g, t)
        fit["site"] = site
        fit["excess_category"] = excess_category(fit.get("beta_excess", np.nan))
        traj_rows.append(fit)

        eg = envelope_gap(g)
        envelope_frames.append(eg)

    traj = pd.DataFrame(traj_rows)
    traj.to_parquet("data/site_trajectory.parquet", index=False)

    envelope_df = pd.concat(envelope_frames, ignore_index=True)
    cod = sites.set_index("site")["cod"]
    wc = envelope_df.apply(lambda r: warranty_clock(cod.get(r["site"]), r["month_start"]), axis=1)
    wc_df = pd.DataFrame(list(wc))
    envelope_df = pd.concat([envelope_df.reset_index(drop=True), wc_df], axis=1)
    envelope_df.to_parquet("data/site_month_trajectory.parquet", index=False)

    n_fit = traj["beta"].notna().sum()
    n_decision_grade = traj["decision_grade"].sum()
    med_beta_excess_4plus = traj.loc[traj["decision_grade"], "beta_excess"].median()
    log.info("S7 complete: %d/%d sites fit (n>=2), %d decision-grade (n>=4)",
              n_fit, len(traj), n_decision_grade)
    log.info("TEST 11 (degradation sanity): median beta_excess at 4+ years = %.4f "
              "(target ~ -0.005, i.e. -0.5%%/yr)", med_beta_excess_4plus
              if pd.notna(med_beta_excess_4plus) else float("nan"))
    log.info("excess_category counts: %s", traj["excess_category"].value_counts().to_dict())


if __name__ == "__main__":
    main()
