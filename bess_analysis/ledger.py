"""R1/R2 event ledger: duration D vs incidence K (maximal runs, 1-month gap tolerance), explicit exposure months."""
import numpy as np
import pandas as pd
from signatures import LEDGER

GAP_TOL = 1
SIGS = list(LEDGER)


def episodes(p):
    p = p.sort_values(["plant_id", "t_idx"]).reset_index(drop=True)
    out = []
    for s in SIGS:
        d = p[p["signature"] == s].copy()
        if d.empty:
            continue
        brk = (d["plant_id"] != d["plant_id"].shift()) | (d["t_idx"].diff() > GAP_TOL + 1)
        d["run"] = brk.cumsum()
        e = d.groupby("run").agg(plant_id=("plant_id", "first"), start_t=("t_idx", "min"), end_t=("t_idx", "max"),
                                 months=("t_idx", "size"), onset_year=("year", "first"), onset_age_yr=("age_yr", "first"),
                                 onset_cum_efc=("cum_efc", "first"), onset_efc_rate=("efc", "first"),
                                 mwh_at_stake=("mwh_at_stake", "sum"), typical_discharge=("discharge", "median"))
        e["signature"] = s
        out.append(e.reset_index(drop=True))
    return pd.concat(out, ignore_index=True)


def build_ledger(p):
    ep = episodes(p)
    scored = p["in_service"] & (p["resp_freq"] == "M") & ~p["signature"].isin(["NO_DATA"])
    ex = p.assign(e=scored.astype(int)).groupby(["plant_id", "year"])["e"].sum().rename("exposure_months").reset_index()
    rows = []
    for s in SIGS:
        d = p[p["signature"] == s]
        a = d.groupby(["plant_id", "year"]).agg(D=("t_idx", "size"), mwh_at_stake=("mwh_at_stake", "sum"),
                                                recoverable_mwh=("recoverable_mwh", "sum"),
                                                rte_pts_lost_max=("rte_pts_lost", "max")).reset_index()
        a["signature"] = s
        rows.append(a)
    led = pd.concat(rows, ignore_index=True)
    k = ep.groupby(["plant_id", "onset_year", "signature"]).size().rename("K").reset_index().rename(columns={"onset_year": "year"})
    grid = ex[ex["exposure_months"] > 0].merge(pd.DataFrame({"signature": SIGS}), how="cross")
    led = grid.merge(led, on=["plant_id", "year", "signature"], how="outer").merge(k, on=["plant_id", "year", "signature"], how="left")
    for c in ["D", "K", "mwh_at_stake", "recoverable_mwh", "exposure_months"]:
        led[c] = led[c].fillna(0)
    led[["D", "K", "exposure_months"]] = led[["D", "K", "exposure_months"]].astype(int)
    led["ledger"] = led["signature"].map(LEDGER)
    lbar = (ep.groupby("signature")["months"].sum() / ep.groupby("signature").size()).rename("L_bar")
    return led, ep, lbar
