"""
S13 - Life data analysis: left-truncated MLE distribution fitting
(Reliability Engineering Addendum, Section 3-4).

Fits 5 candidate distributions (exponential, weibull, gamma, lognormal,
loglogistic) per fault signature against data/life_records.parquet, using a
likelihood that is corrected for left truncation (age_entry_years) and right
censoring (status='S'). Each signature is its own cause-specific hazard
stream (competing-risks framing: a BOS_INTERMITTENT spell does not censor a
site's TRACKER stream - they are fit independently, each on its own clock).

Weibull shape (beta) is the operationally load-bearing number: beta < 1 =
infant mortality / early-life (warranty-relevant, NOT a wear-out signal -
never recommend preventive block replacement), beta ~ 1 = random/constant
hazard (no age signal), beta > 1 = wear-out (age-driven, RVM/preventive-
replacement candidate). That hard rule is enforced in classify_beta().

Also reports a simple MTTR diagnostic (mean episode duration in months, from
data/episodes.parquet) per signature as a calibration cross-check against
the addendum's own reference figures - flagged, not silently corrected, when
it looks anomalous (Section 3's SOILING flag).
"""
import json
import logging

import numpy as np
import pandas as pd
from scipy import optimize, stats

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S13 %(message)s")
log = logging.getLogger("s13")

MIN_DURATION_YEARS = 1.0 / 365.25  # floor for duration==0 (same-month failure at entry)


def _floor_durations(T0, T1):
    T1 = np.maximum(T1, T0 + MIN_DURATION_YEARS * (T1 <= T0))
    return T0, T1


def build_dist(family: str, theta):
    if family == "exponential":
        return stats.expon(scale=theta[0])
    if family == "weibull":
        return stats.weibull_min(c=theta[0], scale=theta[1])
    if family == "gamma":
        return stats.gamma(a=theta[0], scale=theta[1])
    if family == "lognormal":
        return stats.lognorm(s=theta[0], scale=theta[1])
    if family == "loglogistic":
        return stats.fisk(c=theta[0], scale=theta[1])
    raise ValueError(family)


N_PARAMS = {"exponential": 1, "weibull": 2, "gamma": 2, "lognormal": 2, "loglogistic": 2}
BOUNDS = {
    "exponential": [(1e-3, None)],
    "weibull": [(1e-3, 20.0), (1e-3, None)],
    "gamma": [(1e-3, 50.0), (1e-3, None)],
    "lognormal": [(1e-3, 10.0), (1e-3, None)],
    "loglogistic": [(1e-3, 20.0), (1e-3, None)],
}
INIT = {
    "exponential": lambda m: [m],
    "weibull": lambda m: [1.2, m],
    "gamma": lambda m: [1.2, m],
    "lognormal": lambda m: [0.8, m],
    "loglogistic": lambda m: [1.2, m],
}


def neg_log_lik(theta, family, T0, T1, is_failure):
    dist = build_dist(family, theta)
    logsf_T0 = dist.logsf(T0)
    if not np.all(np.isfinite(logsf_T0)):
        return 1e12
    ll = np.where(
        is_failure,
        dist.logpdf(T1),
        dist.logsf(T1),
    ) - logsf_T0
    if not np.all(np.isfinite(ll)):
        return 1e12
    return -ll.sum()


def fit_distribution(family: str, T0, T1, is_failure):
    mean_dur = max(T1[is_failure].mean() if is_failure.any() else T1.mean(), 0.1)
    x0 = INIT[family](mean_dur)
    result = optimize.minimize(
        neg_log_lik, x0=x0, args=(family, T0, T1, is_failure),
        method="L-BFGS-B", bounds=BOUNDS[family],
    )
    loglik = -result.fun
    k = N_PARAMS[family]
    aic = 2 * k - 2 * loglik
    return {
        "family": family, "params": list(result.x), "loglik": loglik, "aic": aic,
        "converged": bool(result.success), "n_params": k,
    }


def classify_beta(beta: float) -> str:
    """Hard classification per the addendum's operational rule: only
    beta > 1 (wear-out) is eligible for preventive-replacement / RVM
    framing. beta < 1 is infant mortality - a warranty conversation, never
    a "replace before it breaks" one."""
    if beta < 0.9:
        return "infant_mortality"
    if beta > 1.1:
        return "wear_out"
    return "random"


def fit_signature(life: pd.DataFrame, signature: str) -> dict:
    sub = life[life["signature"] == signature]
    n_fail = int((sub["status"] == "F").sum())
    if n_fail < config.RELIABILITY["min_failures_to_fit"]:
        log.warning("%s: only %d failures (< min_failures_to_fit=%d) - fit is unreliable, "
                    "flagging rather than pooling in this first pass", signature, n_fail,
                    config.RELIABILITY["min_failures_to_fit"])

    T0 = sub["age_entry_years"].to_numpy(dtype=float)
    T1 = sub["age_at_event_years"].to_numpy(dtype=float)
    T0, T1 = _floor_durations(T0, T1)
    is_failure = (sub["status"] == "F").to_numpy()

    fits = [fit_distribution(fam, T0, T1, is_failure) for fam in config.RELIABILITY["distributions"]]
    fits.sort(key=lambda f: f["loglik"], reverse=True)
    best = fits[0]

    weibull_fit = next(f for f in fits if f["family"] == "weibull")
    beta = weibull_fit["params"][0]
    eta = weibull_fit["params"][1]

    return {
        "signature": signature,
        "n_records": len(sub), "n_failures": n_fail, "n_suspensions": int((sub["status"] == "S").sum()),
        "n_equipment_keys": int(sub["equipment_key"].nunique()),
        "below_min_failures_threshold": n_fail < config.RELIABILITY["min_failures_to_fit"],
        "best_fit": {"family": best["family"], "params": best["params"], "loglik": best["loglik"], "aic": best["aic"]},
        "all_fits": [{"family": f["family"], "loglik": f["loglik"], "aic": f["aic"], "converged": f["converged"]}
                     for f in fits],
        "weibull_beta": beta, "weibull_eta_years": eta,
        "beta_classification": classify_beta(beta),
        "rvm_eligible": beta > 1.1,
    }


def mttr_diagnostic(episodes: pd.DataFrame) -> pd.DataFrame:
    sub = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)]
    return sub.groupby("signature")["n_months"].agg(mttr_months="mean", median_months="median", n="count").reset_index()


def main():
    life = pd.read_parquet("data/life_records.parquet")
    episodes = pd.read_parquet("data/episodes.parquet")

    results = []
    for sig in sorted(config.RELIABILITY_SIGNATURES):
        log.info("fitting %s ...", sig)
        r = fit_signature(life, sig)
        results.append(r)
        log.info("  %-18s best=%-12s loglik=%.1f | weibull beta=%.3f (%s) eta=%.2fyr | rvm_eligible=%s",
                  sig, r["best_fit"]["family"], r["best_fit"]["loglik"],
                  r["weibull_beta"], r["beta_classification"], r["weibull_eta_years"], r["rvm_eligible"])

    mttr = mttr_diagnostic(episodes)
    log.info("MTTR diagnostic (mean episode duration, months) - calibration cross-check, not used in fitting:")
    for row in mttr.itertuples():
        flag = ""
        if row.signature == "TRACKER" and not (3.0 <= row.mttr_months <= 5.0):
            flag = "  [OUT OF EXPECTED RANGE vs addendum reference ~3.9mo]"
        if row.signature == "SOILING" and row.mttr_months > 2.0:
            flag = ("  [ANOMALY: addendum reference is ~1.0mo (soiling should clear fast via "
                    "cleaning); this fleet's SOILING episodes run far longer - investigate signature "
                    "attribution before publishing any soiling-driven forecast or spares plan]")
        log.info("  %-18s mean=%.2fmo median=%.1fmo n=%d%s", row.signature, row.mttr_months,
                  row.median_months, row.n, flag)

    out = {
        "generated_from": "data/life_records.parquet + data/episodes.parquet",
        "config": config.RELIABILITY,
        "signatures": results,
        "mttr_diagnostic": mttr.to_dict(orient="records"),
    }
    with open("data/reliability_fits.json", "w") as f:
        json.dump(out, f, indent=2, default=float)

    fits_flat = pd.DataFrame(results)
    fits_flat.to_parquet("data/reliability_fits_summary.parquet", index=False)

    log.info("S13 complete: %d signatures fit -> data/reliability_fits.json, "
              "data/reliability_fits_summary.parquet", len(results))


if __name__ == "__main__":
    main()
