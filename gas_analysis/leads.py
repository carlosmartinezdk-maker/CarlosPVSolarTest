"""Leads: both indices flag (HRI_own and PRI below threshold) for >= 2 consecutive months, ranked by recoverable USD."""
import sys
import numpy as np
import pandas as pd
from config import ROOT
sys.path.insert(0, str(ROOT.parent))
from crm import customers  # noqa: E402

FLAG_HRI_OWN = 0.95
FLAG_PRI = 0.95
MIN_CONSEC = 2
WASH_OVERDUE_EOH = 8000
WASH_DUE_EOH = 4000
RECENT_MONTHS = 24


def wash_status(eoh_since, seen):
    s = np.select([eoh_since > WASH_OVERDUE_EOH, eoh_since > WASH_DUE_EOH], ["OVERDUE (>8,000 EOH)", "due (4,000-8,000 EOH)"],
                  default="within interval (<4,000 EOH)")
    return pd.Series(s).where(seen, pd.Series(s) + " [no wash observed; clock from COD, upper bound]").to_numpy()


def build(p):
    p = p.sort_values(["plant_id", "cls", "t_idx"]).copy()
    p["both_flag"] = p["scoreable"] & (p["hri_own"] < FLAG_HRI_OWN) & (p["pri"] < FLAG_PRI)
    f = p[p["both_flag"]].copy()
    newser = (f["plant_id"] != f["plant_id"].shift()) | (f["cls"] != f["cls"].shift())
    f["run"] = (newser | (f["t_idx"].diff() != 1)).cumsum()
    runs = f.groupby("run").agg(plant_id=("plant_id", "first"), cls=("cls", "first"), start=("t_idx", "min"),
                                end=("t_idx", "max"), n=("t_idx", "size"))
    runs = runs[runs["n"] >= MIN_CONSEC]
    if runs.empty:
        return pd.DataFrame()
    keep = f[f["run"].isin(runs.index)]
    tmax = p["t_idx"].max()
    g = keep.groupby(["plant_id", "cls"])
    L = g.agg(flag_months=("t_idx", "size"), first_flag=("t_idx", "min"), last_flag=("t_idx", "max"),
              hri_own_mean=("hri_own", "mean"), pri_mean=("pri", "mean"), deficit_pct_mean=("deficit_pct", "mean"),
              excess_mmbtu=("excess_mmbtu", "sum"), waste_usd=("waste_usd", "sum"),
              recoverable_usd=("recoverable_usd", "sum"),
              dominant_signature=("signature", lambda x: x.value_counts().index[0]),
              national_cost_share=("cost_source", lambda x: x.isin(["national", "national_fill"]).mean()),
              plant_cost_share=("cost_source", lambda x: (x == "plant").mean()),
              peer_tier=("peer_tier", "median")).reset_index()
    rec = keep[keep["t_idx"] > tmax - RECENT_MONTHS].groupby(["plant_id", "cls"])["recoverable_usd"].sum() \
        .rename("recoverable_usd_last24m")
    L = L.merge(rec.reset_index(), on=["plant_id", "cls"], how="left").fillna({"recoverable_usd_last24m": 0})
    L["longest_run"] = L.merge(runs.groupby(["plant_id", "cls"])["n"].max().reset_index(), on=["plant_id", "cls"])["n"]
    last = p.groupby(["plant_id", "cls"]).last()[["plant_name", "state", "nerc", "ba", "operator", "nameplate_mw",
                                                   "n_units", "unit_size_mw", "cod_year", "chp_cohort",
                                                   "eoh_since_wash", "wash_seen", "cum_eoh", "duct_burners"]]
    L = L.merge(last.reset_index(), on=["plant_id", "cls"], how="left")
    L = customers.assign(L, L["cls"].map(customers.GAS_SHEET), owner_col="operator", operator_col="operator").drop(columns=["ssi"])
    L["wash_status"] = wash_status(L["eoh_since_wash"].to_numpy(), L["wash_seen"].to_numpy())
    L["recoverable_usd_per_yr"] = L["recoverable_usd_last24m"] / 2
    strong = L["dominant_signature"].isin(["FOULING", "HGP"])
    L["conviction_tier"] = np.select(
        [L["chp_cohort"] | (L["national_cost_share"] > 0.5),
         strong & (L["longest_run"] >= 3) & (L["plant_cost_share"] >= 0.5) & (L["peer_tier"] <= 2),
         strong & (L["longest_run"] >= 3)],
        ["C", "A", "B"], default="C")
    for c in ["first_flag", "last_flag"]:
        L[c] = (L[c] // 12).astype(str) + "-" + (L[c] % 12 + 1).astype(str).str.zfill(2)
    L = L.sort_values(["recoverable_usd_last24m", "recoverable_usd"], ascending=False).reset_index(drop=True)
    L.insert(0, "rank", np.arange(1, len(L) + 1))
    return L
