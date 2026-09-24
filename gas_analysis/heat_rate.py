"""Plant x class x month panel: aggregation (CA/CT allocation), capacity join, HR, LF, QC floors."""
import calendar
import numpy as np
import pandas as pd
from config import CACHE, PM_CLASS, GAS_FUELS
from load_923 import load_all
from load_860_allvintages import gas_capacity, plants
import qc_floors

CHP_THERMAL_SHARE = 0.05   # thermal share above this -> cogeneration cohort
CA_SHARE_MIN_TYPICAL = 0.15   # CC blocks whose steam share is normally at least this
CA_COLLAPSE_FRAC = 0.2         # month's steam share below this fraction of its median -> CA generation missing
MIN_SCORE_LF = 0.02          # below this the monthly HR is dominated by start-up fuel; not scored


def aggregate_923():
    d = load_all()
    d = d[d["pm"].isin(PM_CLASS)].copy()
    d["cls"] = d["pm"].map(PM_CLASS)
    d["is_gas"] = d["fuel"].isin(GAS_FUELS)
    # CA rows carry no fuel of their own in many plants; waste-heat (WH) CA rows belong to the CC block
    keep = d["is_gas"] | ((d["cls"] == "CC") & d["fuel"].isin({"WH", "OTH"}) & (d["pm"] == "CA"))
    d = d[keep]
    d["ca_netgen"] = np.where(d["pm"] == "CA", d["netgen"], 0.0)
    d["ct_mmbtu"] = np.where(d["pm"].isin(["CT", "CS"]), d["elec_mmbtu"], 0.0)
    keys = ["plant_id", "cls", "year", "month"]
    num = d.groupby(keys)[["netgen", "elec_mmbtu", "tot_mmbtu", "quantity", "elec_quantity", "ca_netgen",
                           "ct_mmbtu"]].sum(min_count=1).reset_index()
    attrs = d.sort_values("year").groupby("plant_id")[["plant_name", "operator", "state", "nerc", "ba", "chp"]].last()
    # EIA-923 annual respondents ('A'): monthly values are EIA allocations of an annual total -> no monthly signal
    rf = d.groupby(["plant_id", "year"])["resp_freq"].agg(lambda x: "M" if x.str.contains("M").any() else "A")
    num = num.merge(rf.rename("resp_freq").reset_index(), on=["plant_id", "year"], how="left")
    return num.merge(attrs, on="plant_id", how="left")


def reaggregate(p):
    """Plants with a steam bottoming cycle whose CT fuel is booked on GT rows: GT HR below the floor while the
    plant also carries CA generation. Merge that plant's GT block into CC for the whole plant-year."""
    gt = p[(p["cls"] == "GT") & (p["netgen"] > 0)].copy()
    gt["below"] = gt["elec_mmbtu"] * 1000 / gt["netgen"] < qc_floors.FLOORS["GT"]
    has_ca = p[(p["cls"] == "CC") & (p["ca_netgen"] > 0)][["plant_id", "year"]].drop_duplicates()
    cand = gt.groupby(["plant_id", "year"])["below"].mean().reset_index()
    cand = cand[cand["below"] >= 0.5].merge(has_ca, on=["plant_id", "year"])
    cand["merge"] = True
    p = p.merge(cand[["plant_id", "year", "merge"]], on=["plant_id", "year"], how="left")
    p["merge"] = p["merge"].fillna(False).astype(bool)
    p["reaggregated"] = p["merge"]
    p.loc[p["merge"] & (p["cls"] == "GT"), "cls"] = "CC"
    keys = ["plant_id", "cls", "year", "month"]
    nums = ["netgen", "elec_mmbtu", "tot_mmbtu", "quantity", "elec_quantity", "ca_netgen", "ct_mmbtu"]
    first = ["plant_name", "operator", "state", "nerc", "ba", "chp", "resp_freq"]
    agg = {**{c: "sum" for c in nums}, **{c: "first" for c in first}, "reaggregated": "max"}
    return p.groupby(keys).agg(agg).reset_index(), len(cand)


def join_capacity(p):
    cap = gas_capacity()
    # after re-aggregation the GT capacity of merged plants moves to CC too
    p = p.merge(cap, on=["plant_id", "cls", "year"], how="left")
    miss = p["nameplate_mw"].isna()
    if miss.any():   # borrow the nearest vintage for the same plant x class
        near = cap.sort_values("year")
        fill = p.loc[miss, ["plant_id", "cls", "year"]].reset_index().merge(
            near.drop(columns="year").groupby(["plant_id", "cls"]).last().reset_index(), on=["plant_id", "cls"],
            how="inner").set_index("index")
        for c in fill.columns.difference(["plant_id", "cls", "year"]):
            p.loc[fill.index, c] = fill[c]
        p.loc[fill.index, "cap_from_other_vintage"] = True
    if "cap_from_other_vintage" not in p:
        p["cap_from_other_vintage"] = False
    p["cap_from_other_vintage"] = p["cap_from_other_vintage"].fillna(False).astype(bool)
    return p


def build(force=False):
    f = CACHE / "panel_base.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    p = aggregate_923()
    p, n_merge = reaggregate(p)
    # capacity: for merged plant-years, CC capacity = CC + GT
    cap = gas_capacity()
    merged_py = p.loc[p["reaggregated"] & (p["cls"] == "CC"), ["plant_id", "year"]].drop_duplicates()
    p = join_capacity(p)
    if len(merged_py):
        gtcap = cap[cap["cls"] == "GT"].merge(merged_py, on=["plant_id", "year"])[["plant_id", "year", "nameplate_mw", "summer_mw"]]
        gtcap.columns = ["plant_id", "year", "gt_np", "gt_su"]
        p = p.merge(gtcap, on=["plant_id", "year"], how="left")
        sel = (p["cls"] == "CC") & p["reaggregated"] & p["gt_np"].notna()
        p.loc[sel, "nameplate_mw"] = p.loc[sel, "nameplate_mw"].fillna(0) + p.loc[sel, "gt_np"]
        p.loc[sel, "summer_mw"] = p.loc[sel, "summer_mw"].fillna(0) + p.loc[sel, "gt_su"]
        p = p.drop(columns=["gt_np", "gt_su"])
    p["hours"] = [calendar.monthrange(y, m)[1] * 24 for y, m in zip(p["year"], p["month"])]
    p["hr"] = np.where((p["netgen"] > 0) & (p["elec_mmbtu"] > 0), p["elec_mmbtu"] * 1000 / p["netgen"], np.nan)
    p["lf"] = p["netgen"] / (p["nameplate_mw"] * p["hours"])
    p["eoh"] = p["netgen"] / p["nameplate_mw"]
    p["thermal_share"] = np.where(p["tot_mmbtu"] > 0, (p["tot_mmbtu"] - p["elec_mmbtu"]) / p["tot_mmbtu"], np.nan)
    p = qc_floors.flag(p)
    # CC blocks whose steam (CA) generation disappears from the report while CT fuel continues: heat rate jumps to
    # simple-cycle levels with no physical cause -> quarantine as misallocation (ca_generation_missing)
    p["ca_share"] = np.where((p["cls"] == "CC") & (p["netgen"] > 0), p["ca_netgen"].clip(lower=0) / p["netgen"], np.nan)
    med = p[p["ca_share"] > 0].groupby(["plant_id", "cls"])["ca_share"].median().rename("ca_share_med")
    p = p.merge(med.reset_index(), on=["plant_id", "cls"], how="left")
    ca_missing = (p["cls"] == "CC") & (p["ca_share_med"] >= CA_SHARE_MIN_TYPICAL) \
        & (p["ca_share"] < CA_COLLAPSE_FRAC * p["ca_share_med"]) & (p["qc_hr"] == "ok")
    p.loc[ca_missing, "qc_hr"] = "misallocated"
    p["ca_generation_missing"] = ca_missing
    # CHP cohort at plant x class level: EIA-flagged CHP or median thermal share > 5%
    ts = p.groupby(["plant_id", "cls"])["thermal_share"].median().rename("ts_med").reset_index()
    p = p.merge(ts, on=["plant_id", "cls"], how="left")
    p["chp_cohort"] = (p["ts_med"] > CHP_THERMAL_SHARE) | (p["chp"] == "Y") | (p["chp_860"] == "Y")
    p = p.drop(columns="ts_med")
    p["misalloc_reason"] = np.select(
        [p["qc_hr"] != "misallocated", p["ca_generation_missing"], p["chp_cohort"]],
        ["", "ca_generation_missing", "chp_fuel_allocation"], default="ct_ca_or_prime_mover_allocation")
    p.attrs["n_reaggregated_plant_years"] = n_merge
    pl = plants()[["plant_id", "lat", "lon", "county", "state_860", "nerc_860", "ba_860", "operator_860",
                   "regulatory", "sector"]]
    p = p.merge(pl, on="plant_id", how="left")
    p.to_parquet(f, index=False)
    return p


if __name__ == "__main__":
    p = build(force=True)
    print(p.shape, "reaggregated rows:", p["reaggregated"].sum())
    print(qc_floors.breach_table(p).round(4))
    s = p[(p.qc_hr == "ok")]
    print(s.groupby(["year", "cls"]).hr.median().unstack().round(0))
    for c in ["CC", "GT"]:
        x = s[(s.cls == c) & (s.year == 2025)]
        print(c, "2025 plant-month median", x.hr.median().round(0), "| plant-year (annual) median",
              (x.groupby("plant_id").elec_mmbtu.sum() * 1000 / x.groupby("plant_id").netgen.sum()).median().round(0))
    print("join rate by netgen:", p.assign(j=p.nameplate_mw.notna()).groupby("cls").apply(
        lambda d: (d.netgen.clip(lower=0) * d.j).sum() / d.netgen.clip(lower=0).sum()).round(3))
