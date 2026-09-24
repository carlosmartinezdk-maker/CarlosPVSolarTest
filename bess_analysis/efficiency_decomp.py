"""M2 auxiliary-load decomposition.  Charge = Discharge/eta + P_aux*h  =>  C/D = 1/eta + P_aux*(h/D).
Per site OLS of y=C/D on x=h/D across usable months: eta_true = 1/intercept, P_aux = slope (MW).
Seasonal: one intercept (conversion efficiency is not seasonal) with season-specific slopes
(P_aux_summer / P_aux_shoulder / P_aux_winter); HVAC load = P_aux_summer - P_aux_shoulder.
Rolling 12-month refits give trends in eta_true and P_aux."""
import numpy as np
import pandas as pd
from config import SUMMER, SHOULDER

MIN_MONTHS = 10
MAX_CD = 3.0
MIN_EFC = 0.10                  # discharge above 10% of rated energy (drop near-idle months)
ETA_LO, ETA_HI = 0.5, 1.0
SEASON_MIN_MONTHS = 3
ROLL_WINDOW = 12
ROLL_MIN = 8
TREND_MIN_MONTHS = 24


def usable(p, monthly_only=True):
    m = (p["charge"] > 0) & (p["discharge"] > 0) & (p["charge"] / p["discharge"].where(p["discharge"] > 0) < MAX_CD) \
        & (p["efc"] > MIN_EFC)
    if monthly_only:
        m &= p["resp_freq"] == "M"
    return m


def _ols(x, y):
    X = np.c_[np.ones_like(x), x]
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    r = y - X @ beta
    ss = ((y - y.mean()) ** 2).sum()
    n = len(y)
    s2 = (r @ r) / max(n - 2, 1)
    cov = s2 * np.linalg.pinv(X.T @ X)
    return beta, (1 - (r @ r) / ss) if ss > 0 else np.nan, np.sqrt(np.diag(cov))


def fit_site(d):
    y = (d["charge"] / d["discharge"]).to_numpy(float)
    x = (d["hours"] / d["discharge"]).to_numpy(float)
    (a, b), r2, se = _ols(x, y)
    out = {"n": len(d), "a": a, "P_aux_mw": b, "r2": r2, "se_a": se[0], "se_b": se[1],
           "naive_rte": d["discharge"].sum() / d["charge"].sum(),
           "naive_rte_median_month": (d["discharge"] / d["charge"]).median()}
    out["eta_true"] = 1 / a if a > 0 else np.nan
    out["fit_ok"] = bool(a > 0 and ETA_LO < 1 / a <= ETA_HI)
    # seasonal slopes, common intercept
    mon = d["month"].to_numpy()
    su, sh = np.isin(mon, list(SUMMER)), np.isin(mon, list(SHOULDER))
    wi = ~(su | sh)
    cols = [np.ones_like(x)]
    names = []
    for nm, m in [("summer", su), ("shoulder", sh), ("winter", wi)]:
        if m.sum() >= SEASON_MIN_MONTHS:
            cols.append(x * m)
            names.append(nm)
        else:
            cols.append(None)
    Xs = np.c_[tuple(c for c in cols if c is not None)]
    keep_rows = np.ones(len(y), bool)
    for nm, m in [("summer", su), ("shoulder", sh), ("winter", wi)]:
        if nm not in names:
            keep_rows &= ~m
    if len(names) and keep_rows.sum() > len(names) + 2:
        bs, *_ = np.linalg.lstsq(Xs[keep_rows], y[keep_rows], rcond=None)
        for nm, v in zip(names, bs[1:]):
            out[f"P_aux_{nm}_mw"] = v
    out["hvac_excess_mw"] = out.get("P_aux_summer_mw", np.nan) - out.get("P_aux_shoulder_mw", np.nan)
    return out


def rolling(d):
    d = d.sort_values("t_idx")
    t = d["t_idx"].to_numpy()
    rows = []
    for end in range(t.min() + ROLL_WINDOW - 1, t.max() + 1):
        w = d[(t > end - ROLL_WINDOW) & (t <= end)]
        if len(w) < ROLL_MIN:
            continue
        (a, b), _, _ = _ols((w["hours"] / w["discharge"]).to_numpy(float), (w["charge"] / w["discharge"]).to_numpy(float))
        if a > 0 and ETA_LO < 1 / a <= ETA_HI:
            rows.append((end, 1 / a, b))
    return pd.DataFrame(rows, columns=["t_end", "eta", "paux"])


def _trend(r, col):
    if len(r) < 2 or (r["t_end"].max() - r["t_end"].min()) < 12:
        return np.nan
    return np.polyfit((r["t_end"] - r["t_end"].min()) / 12, r[col], 1)[0]


def decompose(p, monthly_only=True):
    """Naive RTE for comparison = site mean of monthly apparent RTE over all valid months (reproduces the spec's 0.844)."""
    u = p[usable(p, monthly_only)]
    naive = p[p["rte"].notna() & ((p["resp_freq"] == "M") | (not monthly_only))].groupby("plant_id")["rte"].mean()
    rows, rolls = [], []
    for pid, d in u.groupby("plant_id"):
        info = {"plant_id": pid, "usable_months": len(d), "naive_rte_mean_month": naive.get(pid, np.nan)}
        if len(d) >= MIN_MONTHS:
            info.update(fit_site(d))
            span = d["t_idx"].max() - d["t_idx"].min() + 1
            if span >= TREND_MIN_MONTHS:
                r = rolling(d)
                r["plant_id"] = pid
                rolls.append(r)
                info["eta_trend_pts_per_yr"] = _trend(r, "eta") * 100
                base = r["paux"].abs().mean()
                info["paux_trend_pct_per_yr"] = _trend(r, "paux") / base * 100 if base > 0 else np.nan
                info["trend_status"] = "ok"
            else:
                info["trend_status"] = "insufficient_history"
        else:
            info["fit_ok"] = False
            info["trend_status"] = "insufficient_history"
        rows.append(info)
    out = pd.DataFrame(rows)
    return out, (pd.concat(rolls, ignore_index=True) if rolls else pd.DataFrame())
