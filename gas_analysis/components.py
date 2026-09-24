"""Degradation decomposition: EOH / starts proxies, wash detection, and one signature per plant-month.

Signatures (priority order, first match wins, only evaluated on months in deficit vs own-best):
  MISALLOCATED > FUEL_QUALITY > DUCT_FIRING > FOULING > CYCLING > HGP > NONRECOVERABLE > UNATTRIBUTED
Months not in deficit are HEALTHY. Annual EIA-923 respondents carry EIA-allocated monthly values, so monthly
components cannot be resolved for them: their deficit months are ANNUAL_ONLY. Non-scoreable months are NOT_SCORED.
"""
import numpy as np
import pandas as pd
from scipy.stats import spearmanr

DEFICIT_HRI_OWN = 0.95          # HRI_own below this = month in deficit vs own-best
# fouling sawtooth: HRI_own declines >= FOUL_RUN months then steps up >= WASH_STEP
FOUL_RUN = 3
FOUL_MIN_NEG_DIFFS = 2          # of the FOUL_RUN month-on-month changes, at least this many negative
FOUL_MIN_DECLINE = 0.008        # industry trigger: 0.8% heat-rate rise over the run
WASH_STEP = 0.015               # >= 1.5% step up
WASH_PERSIST = 0.5              # next month must hold >= this fraction of the step
WASH_MAX_DLF = 0.25             # a step coinciding with a big LF change is dispatch, not a wash
FOUL_MAX_EPISODE = 12           # months walked back from a wash
FOUL_OPEN_DECLINE = 0.015       # open (unwashed) episode at series end
MAX_GAP_MONTHS = 2              # scoreable-month gaps longer than this break a series segment
# HGP / cycling: rolling window
TREND_WINDOW = 18
TREND_MIN_POINTS = 12
HGP_SLOPE_PER_YR = -0.015       # slope of HRI_own over the window
HGP_MIN_RHO = -0.4              # Spearman(HRI_own, cum_EOH)
CYCLING_RHO_MARGIN = 0.10       # starts correlation must beat EOH correlation by this, or ...
CYCLING_STARTS_PER_KEOH = 40    # ... the window is a cycling duty regime (< 25 full-load hours per start)
# duct firing
DUCT_LF = 0.75
DUCT_GAP = -0.02
# fuel quality
HC_DRIFT_TOL = 0.02
# non-recoverable: annual p90 envelope slope
NONREC_MIN_YEARS = 3
NONREC_SLOPE = -0.003           # per yr; steeper than this counts as non-recoverable state
# starts proxy (heuristic, labelled): full-load-equivalent hours per start by LF regime
HOURS_PER_START = [(0.05, 4), (0.15, 8), (0.40, 24), (0.70, 72), (9.0, 300)]
TYPICAL_LOADING = 0.8

RECOVERY = {"FOULING": 0.85, "HGP": 0.50, "NONRECOVERABLE": 0.0, "CYCLING": 0.0, "DUCT_FIRING": 0.0,
            "FUEL_QUALITY": 0.0, "MISALLOCATED": 0.0, "UNATTRIBUTED": 0.0, "ANNUAL_ONLY": 0.0,
            "HEALTHY": 0.0, "NOT_SCORED": 0.0}
LEDGER = {"FOULING": "fault", "HGP": "fault", "CYCLING": "fault", "DUCT_FIRING": "exposure",
          "FUEL_QUALITY": "exposure", "INTERRUPTIBLE_GAS": "exposure", "NONRECOVERABLE": "state",
          "UNATTRIBUTED": "unattributed", "ANNUAL_ONLY": "unresolved", "MISALLOCATED": "excluded"}


def add_operating_proxies(p):
    p = p.sort_values(["plant_id", "cls", "year", "month"]).copy()
    p["t_idx"] = p["year"] * 12 + p["month"] - 1
    eoh = p["eoh"].clip(lower=0).fillna(0)
    lf = p["lf"].fillna(0)
    hps = np.select([lf < b for b, _ in HOURS_PER_START], [h for _, h in HOURS_PER_START])
    days = p["hours"] / 24
    starts = np.where(eoh > 0, np.minimum(np.ceil(eoh / TYPICAL_LOADING / hps), 2 * days), 0)
    prev_on = eoh.groupby([p["plant_id"], p["cls"]]).shift(1).fillna(0) > 0
    starts = starts + ((eoh > 0) & ~prev_on).astype(int) * (hps > 100)   # baseload restart after an outage
    p["starts_proxy"] = starts
    g = [p["plant_id"], p["cls"]]
    p["cum_eoh_obs"] = eoh.groupby(g).cumsum()
    p["cum_starts_obs"] = p["starts_proxy"].groupby(g).cumsum()
    # backlog before 2019: first-12-observed-months mean EOH x months in service before observation
    first = p.groupby(["plant_id", "cls"]).agg(t0=("t_idx", "min"), cod=("first_op_year", "min"),
                                               codm=("first_op_month", "min")).reset_index()
    rate = p[p.groupby(g).cumcount() < 12].groupby(["plant_id", "cls"])["eoh"].mean().rename("eoh_rate0")
    first = first.merge(rate, on=["plant_id", "cls"], how="left")
    cod_idx = first["cod"] * 12 + first["codm"].fillna(6) - 1
    first["months_before"] = (first["t0"] - cod_idx).clip(lower=0)
    first["eoh_backlog"] = first["months_before"] * first["eoh_rate0"].clip(lower=0).fillna(0)
    p = p.merge(first[["plant_id", "cls", "eoh_backlog"]], on=["plant_id", "cls"], how="left")
    p["cum_eoh"] = p["cum_eoh_obs"] + p["eoh_backlog"].fillna(0)
    p["age_yr"] = (p["year"] + (p["month"] - 0.5) / 12) - (p["first_op_year"] + (p["first_op_month"].fillna(6) - 0.5) / 12)
    return p


def _segments(t):
    br = np.r_[True, np.diff(t) > MAX_GAP_MONTHS + 1]
    return np.cumsum(br)


def _series_signatures(d):
    """d: scoreable monthly-respondent rows of one plant x class, sorted. Returns dict of label arrays."""
    n = len(d)
    h = d["hri_own"].to_numpy(float)
    lf = d["lf"].to_numpy(float)
    t = d["t_idx"].to_numpy(int)
    ceoh = d["cum_eoh"].to_numpy(float)
    cst = d["cum_starts_obs"].to_numpy(float)
    seg = _segments(t)
    foul = np.zeros(n, bool)
    wash = np.zeros(n, bool)
    hgp = np.zeros(n, bool)
    cyc = np.zeros(n, bool)
    for s in np.unique(seg):
        ix = np.where(seg == s)[0]
        hs = h[ix]
        m = len(ix)
        for j in range(FOUL_RUN + 1, m):
            step = hs[j] - hs[j - 1]
            if step < WASH_STEP or abs(lf[ix[j]] - lf[ix[j - 1]]) > WASH_MAX_DLF:
                continue
            run = hs[j - 1 - FOUL_RUN:j]
            diffs = np.diff(run)
            if (diffs < 0).sum() < FOUL_MIN_NEG_DIFFS or run[0] - run[-1] < FOUL_MIN_DECLINE:
                continue
            if j + 1 < m and hs[j + 1] < hs[j - 1] + WASH_PERSIST * step:
                continue
            wash[ix[j]] = True
            k = j - 1          # walk back while (loosely) declining
            while k > 0 and (j - k) < FOUL_MAX_EPISODE and hs[k - 1] >= hs[k] - 0.002:
                k -= 1
            foul[ix[k:j]] = True
        # open episode at segment end
        if m > FOUL_RUN and s == seg.max():
            run = hs[m - 1 - FOUL_RUN:m]
            if (np.diff(run) < 0).sum() >= FOUL_MIN_NEG_DIFFS and run[0] - run[-1] >= FOUL_OPEN_DECLINE:
                foul[ix[m - 1 - FOUL_RUN + 1:m]] = True
        # rolling trend windows for HGP / cycling
        for a in range(0, max(m - TREND_MIN_POINTS + 1, 0)):
            b = min(a + TREND_WINDOW, m)
            w = ix[a:b]
            if len(w) < TREND_MIN_POINTS or wash[w].any():
                continue
            yrs = (t[w] - t[w][0]) / 12
            slope = np.polyfit(yrs, h[w], 1)[0]
            if slope > HGP_SLOPE_PER_YR:
                continue
            r_eoh = spearmanr(h[w], ceoh[w])[0]
            r_st = spearmanr(h[w], cst[w])[0]
            deoh = ceoh[w][-1] - ceoh[w][0]
            spk = (cst[w][-1] - cst[w][0]) / deoh * 1000 if deoh > 0 else np.inf
            cyc_regime = spk >= CYCLING_STARTS_PER_KEOH
            if np.isfinite(r_st) and r_st <= HGP_MIN_RHO and (cyc_regime or (np.isfinite(r_eoh) and r_st < r_eoh - CYCLING_RHO_MARGIN)):
                cyc[w] = True
            elif np.isfinite(r_eoh) and r_eoh <= HGP_MIN_RHO:
                hgp[w] = True
    return {"foul": foul, "wash": wash, "hgp": hgp, "cyc": cyc}


def plant_level(p):
    """Non-recoverable envelope slope and duct-firing test per plant x class (monthly respondents)."""
    s = p[p["scoreable"] & (p["resp_freq"] == "M") & p["hri_own"].notna()]
    rows = []
    for (pid, cls), d in s.groupby(["plant_id", "cls"]):
        env = d.groupby("year")["hri_own"].agg(lambda x: np.percentile(x, 90) if len(x) >= 6 else np.nan).dropna()
        slope = np.polyfit(env.index.values, env.values, 1)[0] if len(env) >= NONREC_MIN_YEARS else np.nan
        hi = d.loc[d["lf"] > DUCT_LF, "hri_own"]
        mid = d.loc[d["lf"].between(0.4, DUCT_LF), "hri_own"]
        gap = hi.median() - mid.median() if len(hi) >= 3 and len(mid) >= 3 else np.nan
        rows.append({"plant_id": pid, "cls": cls, "nonrec_slope_per_yr": slope, "n_env_years": len(env),
                     "duct_gap": gap})
    return pd.DataFrame(rows)


def assign(p):
    p = add_operating_proxies(p)
    pl = plant_level(p)
    p = p.merge(pl, on=["plant_id", "cls"], how="left")
    for c in ["foul", "wash", "hgp", "cyc"]:
        p[c] = False
    mon = p["scoreable"] & (p["resp_freq"] == "M") & p["hri_own"].notna()
    for _, d in p[mon].groupby(["plant_id", "cls"]):
        r = _series_signatures(d)
        for c, v in r.items():
            p.loc[d.index, c] = v
    deficit = p["hri_own"] < DEFICIT_HRI_OWN
    duct = (p["duct_burners"] == "Y") & (p["duct_gap"] <= DUCT_GAP) & (p["lf"] > DUCT_LF)
    fuelq = (p["heat_content_drift"] - 1).abs() >= HC_DRIFT_TOL
    nonrec = p["nonrec_slope_per_yr"] <= NONREC_SLOPE
    sig = np.select(
        [p["qc_hr"] == "misallocated",
         ~p["scoreable"],
         ~deficit.fillna(False),
         p["resp_freq"] != "M",
         fuelq.fillna(False), duct, p["foul"], p["cyc"], p["hgp"], nonrec.fillna(False)],
        ["MISALLOCATED", "NOT_SCORED", "HEALTHY", "ANNUAL_ONLY",
         "FUEL_QUALITY", "DUCT_FIRING", "FOULING", "CYCLING", "HGP", "NONRECOVERABLE"],
        default="UNATTRIBUTED")
    p["signature"] = sig
    # fouling episodes are recoverable degradation whether or not the month crossed the deficit line
    p.loc[p["foul"] & p["scoreable"] & (p["resp_freq"] == "M") & (p["signature"] == "HEALTHY")
          & (p["hri_own"] < 1.0), "signature"] = "FOULING"
    p["recovery"] = p["signature"].map(RECOVERY).fillna(0.0)
    return add_wash_clock(p)


def add_wash_clock(p):
    """EOH since last apparent wash (reset at detected wash months). Before the first detected wash the clock runs
    from COD (backlog estimate), so it is an upper bound when no wash is visible."""
    p = p.sort_values(["plant_id", "cls", "t_idx"])
    eoh = p["eoh"].clip(lower=0).fillna(0)
    grp = p["wash"].astype(int).groupby([p["plant_id"], p["cls"]]).cumsum()
    since = eoh.groupby([p["plant_id"], p["cls"], grp]).cumsum()
    p["eoh_since_wash"] = np.where(grp == 0, since + p["eoh_backlog"].fillna(0), since)
    p["wash_seen"] = grp > 0
    return p
