"""M4 load-factor reference curve (p10 per LF bin, monotone), M6 HRI, M8 own-best baseline."""
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression

LF_EDGES = np.array([0.0, 0.05, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 1.0, 1.1])
REF_PCTL = 10
MIN_SCORE_LF = 0.02
MAX_SCORE_LF = 1.10
OWN_WINDOW = 24          # first N scoreable months define the own-best baseline
OWN_PCTL = 95
OWN_MIN_MONTHS = 6       # fewer scoreable months in the window -> no own baseline


def scoreable(p):
    return (p["qc_hr"] == "ok") & p["lf"].between(MIN_SCORE_LF, MAX_SCORE_LF) & p["hr_corr"].notna()


def fit_curves(p):
    """Per class: p10 of HR_corr within LF bins on the non-CHP fleet, then isotonic (non-increasing in LF)."""
    base = p[scoreable(p) & ~p["chp_cohort"]]
    rows = []
    for cls, d in base.groupby("cls"):
        b = pd.cut(d["lf"], LF_EDGES, labels=False, include_lowest=True)
        t = d.groupby(b).agg(n=("hr_corr", "size"), p10=("hr_corr", lambda x: np.percentile(x, REF_PCTL)),
                             p10_raw=("hr", lambda x: np.percentile(x, REF_PCTL)),
                             p50=("hr_corr", "median"), lf_mid=("lf", "median")).reset_index(names="bin")
        iso = IsotonicRegression(increasing=False).fit(t["lf_mid"], t["p10"], sample_weight=np.sqrt(t["n"]))
        t["ref"] = iso.predict(t["lf_mid"])
        t["cls"] = cls
        t["lf_lo"], t["lf_hi"] = LF_EDGES[t["bin"]], LF_EDGES[t["bin"] + 1]
        rows.append(t)
    return pd.concat(rows, ignore_index=True)


def hr_ref(p, curves):
    out = np.full(len(p), np.nan)
    for cls, c in curves.groupby("cls"):
        m = (p["cls"] == cls).values
        out[m] = np.interp(p.loc[m, "lf"].clip(c["lf_mid"].min(), c["lf_mid"].max()), c["lf_mid"], c["ref"])
    return out


def add_indices(p, curves):
    p["hr_ref"] = hr_ref(p, curves)
    sc = scoreable(p)
    p["scoreable"] = sc
    p["hri"] = np.where(sc, p["hr_ref"] / p["hr_corr"], np.nan)
    # own-best baseline over first 24 scoreable months
    p = p.sort_values(["plant_id", "cls", "year", "month"])
    p["score_seq"] = p["scoreable"].astype(int).groupby([p["plant_id"], p["cls"]]).cumsum()
    win = p[p["scoreable"] & (p["score_seq"] <= OWN_WINDOW)]
    eta = win.groupby(["plant_id", "cls"])["hri"].agg(
        eta_own=lambda x: np.percentile(x, OWN_PCTL) if len(x) >= OWN_MIN_MONTHS else np.nan,
        own_n="size").reset_index()
    p = p.drop(columns=[c for c in ["eta_own", "own_n"] if c in p.columns]).merge(eta, on=["plant_id", "cls"], how="left")
    p["hri_own"] = p["hri"] / p["eta_own"]
    return p
