"""Plant x month BESS panel: charge, discharge, time-varying E_rated, duration band, RTE, EFC, temperature."""
import calendar
import numpy as np
import pandas as pd
from config import CACHE
from load_storage import battery_monthly
from load_860_allvintages import plant_year, plants
import hybrid_filter
from weather import plant_monthly_temps

RTE_MAX = 1.2
SOC_DRIFT = 0.5                 # |D - C| / C above this -> state-of-charge drift, RTE unreliable
DUR_BANDS = [0, 1.5, 2.5, 4.5, 1e9]
DUR_LABELS = ["<1.5h", "1.5-2.5h", "2.5-4.5h", ">4.5h"]
ZERO_MWH = 1.0                  # |throughput| below this is 'approximately zero'


def build(force=False):
    f = CACHE / "bess_panel_base.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    b = battery_monthly()
    py = plant_year()
    p = b.merge(py, on=["plant_id", "year"], how="left")
    miss = p["e_rated_mwh"].isna()
    p["cap_from_other_vintage"] = False
    if miss.any():     # plant not in that vintage's 860 (commissioned late / reporting lag): nearest vintage
        near = py.sort_values("year")
        for idx, r in p[miss].iterrows():
            c = near[near["plant_id"] == r["plant_id"]]
            if len(c):
                j = (c["year"] - r["year"]).abs().idxmin()
                for col in py.columns.difference(["plant_id", "year"]):
                    p.at[idx, col] = c.at[j, col]
                p.at[idx, "cap_from_other_vintage"] = True
    p["hours"] = [calendar.monthrange(y, m)[1] * 24 for y, m in zip(p["year"], p["month"])]
    p["t_idx"] = p["year"] * 12 + p["month"] - 1
    p["charge"] = p["charge"].clip(lower=0)
    p["discharge"] = p["discharge"].clip(lower=0)
    rte = p["discharge"] / p["charge"].where(p["charge"] > 0)
    p["rte"] = rte.where((rte > 0) & (rte <= RTE_MAX))
    p["soc_drift"] = ((p["discharge"] - p["charge"]).abs() / p["charge"].where(p["charge"] > 0)) > SOC_DRIFT
    p["efc"] = p["discharge"] / p["e_rated_mwh"].where(p["e_rated_mwh"] > 0)
    p["dur_band"] = pd.cut(p["duration_h"], DUR_BANDS, labels=DUR_LABELS, right=False).astype(str)
    p["age_yr"] = p["year"] + (p["month"] - 0.5) / 12 - (p["op_year_min"] + (pd.to_numeric(p["op_month_first"], errors="coerce").fillna(6) - 0.5) / 12)
    from load_860_allvintages import generators
    g = generators()
    g = g[g["pm"] == "BA"]
    last_v = g.groupby("plant_id")["vintage"].max()
    retired = g[g["retire_year"].notna()].groupby("plant_id")["vintage"].max()
    ret = (retired.reindex(last_v.index) == last_v) & ~g[g["retire_year"].isna()].groupby("plant_id")["vintage"].max() \
        .reindex(last_v.index).eq(last_v)
    p = p.merge(ret.rename("retired_site").reset_index(), on="plant_id", how="left")
    hy = hybrid_filter.flags(p, py)
    p = p.merge(hy, on="plant_id", how="left")
    pl = plants()[["plant_id", "lat", "lon", "county", "state_860", "ba_860", "operator_860"]]
    p = p.merge(pl, on="plant_id", how="left")
    t = plant_monthly_temps(p["plant_id"].unique())
    p = p.merge(t, on=["plant_id", "year", "month"], how="left")
    p.to_parquet(f, index=False)
    return p


if __name__ == "__main__":
    p = build(force=True)
    print(p.shape, "plants", p.plant_id.nunique())
    print("join rate (plant-months with E_rated):", p.e_rated_mwh.notna().mean().round(4),
          "same vintage:", (p.e_rated_mwh.notna() & ~p.cap_from_other_vintage).mean().round(4))
    s = p.drop_duplicates("plant_id")
    print("hybrids:", s.hybrid.sum(), "of", len(s)); print(s[["rte_gt_1", "colocated_firming", "pv_same_plant", "dc_coupled"]].sum())
    print("temp coverage", p.t_amb_c.notna().mean().round(4))
    for hyb in [False, True]:
        x = p[(p.year == 2025) & (p.hybrid == hyb)]
        a = x.groupby("plant_id")[["charge", "discharge"]].sum()
        a = a[a.charge > 0]
        print("hybrid" if hyb else "standalone", "2025 median annual RTE", (a.discharge / a.charge).median().round(3),
              "| median monthly RTE", x.rte.median().round(3), "| fleet-sum RTE", (a.discharge.sum() / a.charge.sum()).round(3), "n", len(a))
