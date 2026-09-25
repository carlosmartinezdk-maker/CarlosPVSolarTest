"""Inspection leads: decision-matrix bottom-right (eta_true low AND throughput low vs peers -> availability) plus
availability signatures and elevated / rising P_aux, persistent >= 2 consecutive months. Ranked by MWh at stake
(last 24 months) and warranty headroom remaining."""
import sys
import numpy as np
import pandas as pd
from config import ROOT
sys.path.insert(0, str(ROOT.parent))
from crm import customers  # noqa: E402
from signatures import ETA_OK, UTI_LOW, PAUX_BAND_PCT

MIN_CONSEC = 2
RECENT = 24
MIN_PLAUSIBLE_DURATION_H = 0.25    # E_rated/MW below this is an EIA-860 energy-capacity error
TECH = ["FULL_OUTAGE", "PARTIAL_AVAILABILITY", "THERMAL_AUX"]


def build(p):
    p = p.sort_values(["plant_id", "t_idx"]).copy()
    paux_pct = p["P_aux_mw"] / p["nameplate_mw"] * 100
    quad = p["fit_ok"].fillna(False).astype(bool) & (p["eta_true"] < ETA_OK) & (p["uti"] < UTI_LOW)
    elevated = p["fit_ok"].fillna(False).astype(bool) & (paux_pct > PAUX_BAND_PCT) & p["deficit"]
    p["lead_flag"] = (p["signature"].isin(TECH) | quad | elevated) & p["in_service"] & (p["resp_freq"] == "M")
    p["lead_reason"] = np.select([p["signature"].isin(TECH), quad, elevated],
                                 [p["signature"], "LOW_ETA_AND_LOW_UTI", "ELEVATED_P_AUX"], default="")
    f = p[p["lead_flag"]].copy()
    f["run"] = ((f["plant_id"] != f["plant_id"].shift()) | (f["t_idx"].diff() != 1)).cumsum()
    runs = f.groupby("run").agg(plant_id=("plant_id", "first"), n=("t_idx", "size"))
    runs = runs[runs["n"] >= MIN_CONSEC]
    k = f[f["run"].isin(runs.index)]
    tmax = p["t_idx"].max()
    L = k.groupby("plant_id").agg(flag_months=("t_idx", "size"), first_flag=("t_idx", "min"), last_flag=("t_idx", "max"),
                                  dominant_reason=("lead_reason", lambda x: x.value_counts().index[0]),
                                  mwh_at_stake=("mwh_at_stake", "sum")).reset_index()
    L["longest_run"] = L["plant_id"].map(runs.groupby("plant_id")["n"].max())
    L["mwh_at_stake_last24m"] = L["plant_id"].map(k[k["t_idx"] > tmax - RECENT].groupby("plant_id")["mwh_at_stake"].sum()).fillna(0)
    last = p.groupby("plant_id").last()[["plant_name", "state", "ba", "operator", "nameplate_mw", "e_rated_mwh",
                                         "duration_h", "dur_band", "cod_year", "chem", "enclosure", "hybrid",
                                         "hybrid_reasons", "eta_true", "P_aux_mw", "cum_efc", "throughput_used"]]
    L = L.merge(last.reset_index(), on="plant_id", how="left")
    L = customers.assign(L, "BESS", owner_col="operator", operator_col="operator").drop(columns=["ssi"])
    L["P_aux_pct_nameplate"] = L["P_aux_mw"] / L["nameplate_mw"] * 100
    L["warranty_headroom"] = (1 - L["throughput_used"]).clip(lower=0)
    L["implausible_e_rated"] = L["duration_h"] < MIN_PLAUSIBLE_DURATION_H
    L["conviction_tier"] = np.select([L["hybrid"] | L["implausible_e_rated"], (L["longest_run"] >= 3) & L["eta_true"].notna()],
                                     ["C", "A"], default="B")
    for c in ["first_flag", "last_flag"]:
        L[c] = (L[c] // 12).astype(str) + "-" + (L[c] % 12 + 1).astype(str).str.zfill(2)
    L = L.sort_values(["mwh_at_stake_last24m", "warranty_headroom"], ascending=False).reset_index(drop=True)
    L.insert(0, "rank", np.arange(1, len(L) + 1))
    return L
