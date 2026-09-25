"""Site-month fault signatures (first match wins) plus M5 availability, M6 fade, M7 asymmetry, M8 warranty.

 1 FULL_OUTAGE          charge ~0 and discharge ~0 while peer median EFC > 0.5            recovery 0.90
 2 AUGMENTATION         step increase in E_rated between 860 vintages, or EPC envelope +15% 0.00 (scheduled capex)
 3 PARTIAL_AVAILABILITY UTI at a quantised fraction (N-1)/N or 1/2 of its trailing 6-month
                        median, flat >= 2 months, step onset                                0.85
 4 THERMAL_AUX          HVAC excess (P_aux summer - shoulder) above fleet p90 for the
                        enclosure type, or P_aux trending up > 20%/yr                       0.70
 5 CELL_DEGRADATION     eta_true declining >= 1.5 pts/yr with throughput unaffected         0.25
 6 CAPACITY_FADE        EPC envelope declining > 3%/yr vs time-varying E_rated, >= 24 mo   0.25
 7 UNDER_DISPATCH       eta_true >= 0.86 but UTI < 0.60                                     0.00 (commercial)
 8 HYBRID_ARTEFACT      hybrid site (rules 4-6 need clean efficiency and are skipped)       0.00 (data issue)
 9 UNATTRIBUTED         deficit present, nothing above fires                                0.30
 0 HEALTHY
Months outside the in-service window are NOT_IN_SERVICE; EIA-923 annual-respondent months (EIA-allocated monthly
values) are ANNUAL_RESPONDENT and are not scored for monthly signatures.
"""
import numpy as np
import pandas as pd
from config import SUMMER

ETA_OK = 0.86
UTI_OK = 0.75
UTI_LOW = 0.60
PAUX_BAND_PCT = 1.0            # P_aux above this % of nameplate is outside the normal band (fleet p90 ~0.85%)
OUTAGE_PEER_EFC = 0.5
ZERO_MWH = 1.0
AUG_E_STEP = 0.05              # E_rated vintage-on-vintage increase counted as augmentation
EPC_STEP = 0.15
PARTIAL_FRACTIONS = [1 / 2, 2 / 3, 3 / 4, 4 / 5, 5 / 6, 7 / 8]
PARTIAL_TOL = 0.04
PARTIAL_FLAT = 0.06
PARTIAL_MIN_MONTHS = 2
TRAIL = 6
THERMAL_PCTL = 90
PAUX_TREND_PCT = 20.0
CELL_DEG_PTS = -1.5
FADE_PCT = -3.0
FADE_MIN_MONTHS = 24
FADE_MIN_EFC = 0.5
RTE_DEFICIT_PTS = 0.05         # monthly apparent RTE this far below its duration-band median -> deficit
WARRANTY_CYCLES = 6000         # assumed contracted cycle life when unknown (flagged)
ENVELOPE_C = (-10.0, 30.0)     # assumed operating envelope on monthly mean ambient (flagged)

RECOVERY = {"FULL_OUTAGE": 0.90, "AUGMENTATION": 0.0, "PARTIAL_AVAILABILITY": 0.85, "THERMAL_AUX": 0.70,
            "CELL_DEGRADATION": 0.25, "CAPACITY_FADE": 0.25, "UNDER_DISPATCH": 0.0, "HYBRID_ARTEFACT": 0.0,
            "UNATTRIBUTED": 0.30, "HEALTHY": 0.0, "NO_DATA": 0.0,
            "NOT_IN_SERVICE": 0.0, "ANNUAL_RESPONDENT": 0.0}
LEDGER = {"FULL_OUTAGE": "fault", "PARTIAL_AVAILABILITY": "fault", "THERMAL_AUX": "fault", "UNATTRIBUTED": "fault",
          "UNDER_DISPATCH": "exposure", "HYBRID_ARTEFACT": "exposure", "AUGMENTATION": "exposure",
          "CELL_DEGRADATION": "state", "CAPACITY_FADE": "state"}


def fade(p):
    """M6: EPC = D / max(1, round(EFC)), normalised by time-varying E_rated; log-linear slope of the 12-month rolling
    p90. Also flags EPC envelope step-ups > 15% (augmentation)."""
    rows, steps = [], []
    for pid, d in p.sort_values("t_idx").groupby("plant_id"):
        d = d[d["e_rated_mwh"] > 0]
        epc = d["discharge"] / np.maximum(1, np.round(d["efc"].fillna(0)))
        en = (epc / d["e_rated_mwh"]).where(d["discharge"] > 0)
        s = pd.Series(en.to_numpy(), index=d["t_idx"].to_numpy())
        s = s.reindex(range(int(s.index.min()), int(s.index.max()) + 1)) if len(s) else s
        env = s.rolling(12, min_periods=6).quantile(0.9)
        good_share = (d["efc"] >= FADE_MIN_EFC).mean() if len(d) else 0
        span = len(s)
        info = {"plant_id": pid, "fade_months": span, "fade_efc_share": good_share}
        if span >= FADE_MIN_MONTHS and good_share > 0.5 and env.notna().sum() >= 12:
            e = env.dropna()
            e = e[e > 0]
            info["fade_pct_per_yr"] = (np.exp(np.polyfit((e.index - e.index.min()) / 12, np.log(e), 1)[0]) - 1) * 100
            info["fade_status"] = "ok"
        else:
            info["fade_pct_per_yr"] = np.nan
            info["fade_status"] = "insufficient_history"
        rows.append(info)
        r = env / env.shift(12)
        for t in r.index[(r > 1 + EPC_STEP).fillna(False).to_numpy()]:
            steps.append((pid, int(t)))
    return pd.DataFrame(rows), pd.DataFrame(steps, columns=["plant_id", "t_idx"]).drop_duplicates("plant_id", keep="first")


def availability(p):
    """M5 partial availability: UTI relative to own trailing-6-month median sits at a quantised fraction, flat for
    >= 2 months, with a step onset."""
    p = p.sort_values(["plant_id", "t_idx"]).copy()
    g = p.groupby("plant_id")["uti"]
    trail = g.transform(lambda x: x.shift(1).rolling(TRAIL, min_periods=4).median())
    r = p["uti"] / trail
    p["uti_rel"] = r
    near = np.zeros(len(p), bool)
    for f in PARTIAL_FRACTIONS:
        near |= (r - f).abs().to_numpy() <= PARTIAL_TOL
    near &= p["discharge"].to_numpy() > ZERO_MWH
    p["_near"] = near
    prev_r = r.groupby(p["plant_id"]).shift(1)
    next_r = r.groupby(p["plant_id"]).shift(-1)
    next_near = p.groupby("plant_id")["_near"].shift(-1).fillna(False).astype(bool)
    prev_near = p.groupby("plant_id")["_near"].shift(1).fillna(False).astype(bool)
    onset = near & (prev_r >= 0.9).to_numpy() & next_near.to_numpy() & ((next_r - r).abs() <= PARTIAL_FLAT).to_numpy()
    # propagate: an onset month and the following flat near-fraction months
    part = np.zeros(len(p), bool)
    pid = p["plant_id"].to_numpy()
    for i in np.where(onset)[0]:
        j = i
        while j < len(p) and pid[j] == pid[i] and near[j] and (j == i or abs(r.iat[j] - r.iat[i]) <= PARTIAL_FLAT):
            part[j] = True
            j += 1
    p["partial_avail"] = part
    return p.drop(columns="_near")


def warranty(p):
    p = p.sort_values(["plant_id", "t_idx"]).copy()
    efc = p["efc"].fillna(0).clip(lower=0)
    p["cum_efc_obs"] = efc.groupby(p["plant_id"]).cumsum()
    first = p.groupby("plant_id").agg(t0=("t_idx", "min"), y0=("op_year_min", "first"),
                                      m0=("op_month_first", "first")).reset_index()
    rate = p[p.groupby("plant_id").cumcount() < 12].groupby("plant_id")["efc"].mean().rename("efc_rate0")
    first = first.merge(rate, on="plant_id", how="left")
    cod_idx = first["y0"] * 12 + pd.to_numeric(first["m0"], errors="coerce").fillna(6) - 1
    first["efc_backlog"] = (first["t0"] - cod_idx).clip(lower=0) * first["efc_rate0"].clip(lower=0).fillna(0)
    p = p.merge(first[["plant_id", "efc_backlog"]], on="plant_id", how="left")
    p["cum_efc"] = p["cum_efc_obs"] + p["efc_backlog"].fillna(0)
    p["throughput_used"] = p["cum_efc"] / WARRANTY_CYCLES
    p["envelope_breach"] = (p["t_amb_c"] < ENVELOPE_C[0]) | (p["t_amb_c"] > ENVELOPE_C[1])
    return p


def assign(p, dec, fd):
    """p: panel with UTI; dec: efficiency decomposition per site; fd: fade table."""
    p = p.merge(dec[["plant_id", "eta_true", "P_aux_mw", "hvac_excess_mw", "eta_trend_pts_per_yr",
                     "paux_trend_pct_per_yr", "fit_ok"]], on="plant_id", how="left")
    p = p.merge(fd[["plant_id", "fade_pct_per_yr", "fade_status"]], on="plant_id", how="left")
    p = availability(p)
    p = warranty(p)
    # thermal / aux: HVAC excess above the fleet p90 of its enclosure type (standalone, fitted sites)
    site = p.drop_duplicates("plant_id")
    base = site[site["fit_ok"].fillna(False).astype(bool) & ~site["hybrid"]]
    p90 = base.groupby("enclosure")["hvac_excess_mw"].quantile(THERMAL_PCTL / 100)
    p90_mw_per_mw = (base["hvac_excess_mw"] / base["nameplate_mw"]).quantile(THERMAL_PCTL / 100)
    thr = p["enclosure"].map(p90)
    hv = (p["hvac_excess_mw"] > thr) | ((p["hvac_excess_mw"] / p["nameplate_mw"]) > p90_mw_per_mw) & thr.isna()
    p["thermal_site"] = (hv | (p["paux_trend_pct_per_yr"] > PAUX_TREND_PCT)).fillna(False) & p["fit_ok"].fillna(False).astype(bool)
    p["cell_deg_site"] = (p["eta_trend_pts_per_yr"] <= CELL_DEG_PTS).fillna(False)
    p["fade_site"] = (p["fade_pct_per_yr"] < FADE_PCT).fillna(False)
    # augmentation: first month of a vintage whose E_rated rose > 5%, or EPC envelope step-up
    er = p.drop_duplicates(["plant_id", "year"])[["plant_id", "year", "e_rated_mwh"]].sort_values(["plant_id", "year"])
    er["prev"] = er.groupby("plant_id")["e_rated_mwh"].shift(1)
    er["aug_year"] = er["e_rated_mwh"] > er["prev"] * (1 + AUG_E_STEP)
    p = p.merge(er[["plant_id", "year", "aug_year"]], on=["plant_id", "year"], how="left")
    first_m = p.groupby(["plant_id", "year"])["t_idx"].transform("min")
    aug = (p["aug_year"].fillna(False) & (p["t_idx"] == first_m))
    _, steps = fade(p)
    if len(steps):
        aug |= pd.Series(list(zip(p["plant_id"], p["t_idx"]))).isin(set(map(tuple, steps.to_numpy()))).to_numpy()
    p["augmentation"] = aug
    # deficit present
    band_med = p[~p["hybrid"]].groupby(["dur_band", "year"])["rte"].median().rename("band_rte_med")
    p = p.merge(band_med.reset_index(), on=["dur_band", "year"], how="left")
    paux_pct = p["P_aux_mw"] / p["nameplate_mw"] * 100
    eta_known = p["eta_true"].notna() & p["fit_ok"].fillna(False).astype(bool)
    deficit = ((eta_known & (p["eta_true"] < ETA_OK)) | (p["uti"] < UTI_OK) | (paux_pct > PAUX_BAND_PCT)
               | (p["rte"] < p["band_rte_med"] - RTE_DEFICIT_PTS)).fillna(False)
    zero = (p["charge"].fillna(0) < ZERO_MWH) & (p["discharge"].fillna(0) < ZERO_MWH)
    outage = zero & (p["peer_efc_median"] > OUTAGE_PEER_EFC)
    hyb = p["hybrid"].fillna(False)
    summer = p["month"].isin(SUMMER)
    thermal_m = p["thermal_site"] & deficit & (summer | (p["paux_trend_pct_per_yr"] > PAUX_TREND_PCT).fillna(False))
    effok = ~hyb
    underd = ((eta_known & (p["eta_true"] >= ETA_OK)) | ~eta_known) & (p["uti"] < UTI_LOW)
    nodata = p["charge"].isna() & p["discharge"].isna()
    act = (p["charge"].fillna(0) >= ZERO_MWH) | (p["discharge"].fillna(0) >= ZERO_MWH)
    t_first = p["t_idx"].where(act).groupby(p["plant_id"]).transform("min")
    t_last = p["t_idx"].where(act).groupby(p["plant_id"]).transform("max")
    # trailing zeros after the last active month stay in service (a live outage) unless 860 lists the site retired
    end = np.where(p["retired_site"].fillna(False), t_last, p["t_idx"].max())
    p["in_service"] = (p["t_idx"] >= t_first) & (p["t_idx"] <= end)
    annual = p["resp_freq"] != "M"
    p["deficit"] = deficit
    p["signature"] = np.select(
        [nodata, ~p["in_service"], annual, outage, p["augmentation"], p["partial_avail"],
         effok & thermal_m, effok & p["cell_deg_site"] & deficit & (p["uti"] >= UTI_OK),
         effok & p["fade_site"] & deficit, effok & underd, hyb, deficit],
        ["NO_DATA", "NOT_IN_SERVICE", "ANNUAL_RESPONDENT", "FULL_OUTAGE", "AUGMENTATION", "PARTIAL_AVAILABILITY", "THERMAL_AUX", "CELL_DEGRADATION",
         "CAPACITY_FADE", "UNDER_DISPATCH", "HYBRID_ARTEFACT", "UNATTRIBUTED"], default="HEALTHY")
    p["recovery"] = p["signature"].map(RECOVERY).fillna(0)
    return mwh_at_stake(p)


def mwh_at_stake(p):
    """MWh at stake per month by signature (never dollars: no nodal price model)."""
    p = p.sort_values(["plant_id", "t_idx"])
    trail = p.groupby("plant_id")["discharge"].transform(lambda x: x.shift(1).rolling(6, min_periods=3).median())
    peer_exp = p["peer_efc_median"] * p["e_rated_mwh"]
    expected = trail.fillna(peer_exp)
    shortfall = (expected - p["discharge"].fillna(0)).clip(lower=0)
    eff_loss = (p["charge"] - p["discharge"] / p["band_rte_med"]).clip(lower=0)
    fleet_paux_pct = (p["P_aux_mw"] / p["nameplate_mw"]).median()
    aux_excess = ((p["P_aux_mw"] - fleet_paux_pct * p["nameplate_mw"]).clip(lower=0) * p["hours"])
    hv = (p["hvac_excess_mw"].clip(lower=0) * p["hours"])
    s = p["signature"]
    p["mwh_at_stake"] = np.select(
        [s.isin(["FULL_OUTAGE", "PARTIAL_AVAILABILITY"]), s == "THERMAL_AUX",
         s.isin(["CELL_DEGRADATION", "CAPACITY_FADE", "UNATTRIBUTED"]),
         s == "UNDER_DISPATCH"],
        [shortfall, np.fmax(aux_excess.fillna(0), hv.fillna(0)), eff_loss, (peer_exp - p["discharge"]).clip(lower=0)],
        default=0.0)
    p["mwh_at_stake"] = p["mwh_at_stake"].fillna(0)
    p["recoverable_mwh"] = p["mwh_at_stake"] * p["recovery"]
    p["rte_pts_lost"] = np.where(s.isin(["THERMAL_AUX", "CELL_DEGRADATION", "CAPACITY_FADE", "UNATTRIBUTED"]),
                                 (p["band_rte_med"] - p["rte"]).clip(lower=0) * 100, 0.0)
    return p
