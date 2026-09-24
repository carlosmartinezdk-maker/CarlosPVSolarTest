"""Excess fuel and cost vs an attainable target (peer p75 HRI at the same load factor), recovery and payback.
Dollars are indicative only: recovery fractions and remediation costs are UNVALIDATED placeholders."""
import numpy as np
import pandas as pd
from config import ROOT
from reference import LF_EDGES

TARGET_PCTL = 75
HORIZON_YR = 3                     # preventative-decision horizon (R7)
COST_TABLE = ROOT / "inputs" / "remediation_costs.csv"


def attach_fuel_cost(p, fc):
    p = p.merge(fc, on=["plant_id", "year", "month"], how="left")
    # plants without Page 5 receipts: state-month median of the file's state series, else national
    st = fc.merge(p[["plant_id", "state"]].drop_duplicates("plant_id"), on="plant_id")
    st = st[st["cost_source"] != "national"].groupby(["state", "year", "month"])["gas_cost_final"].median() \
        .rename("state_fill").reset_index()
    nat = fc.groupby(["year", "month"])["natl_cost"].mean().rename("natl_fill").reset_index()
    p = p.drop(columns=["natl_cost"]).merge(st, on=["state", "year", "month"], how="left") \
        .merge(nat, on=["year", "month"], how="left")
    miss = p["gas_cost_final"].isna()
    use_st = miss & p["state_fill"].notna()
    p.loc[use_st, "gas_cost_final"] = p.loc[use_st, "state_fill"]
    p.loc[use_st, "cost_source"] = "state_fill"
    miss = p["gas_cost_final"].isna()
    p.loc[miss, "gas_cost_final"] = p.loc[miss, "natl_fill"]
    p.loc[miss, "cost_source"] = "national_fill"
    return p.drop(columns=["state_fill", "natl_fill"])


def add_excess(p):
    b = pd.cut(p["lf"], LF_EDGES, labels=False, include_lowest=True)
    p["lf_bin"] = b
    base = p[p["scoreable"] & ~p["chp_cohort"]]
    t = base.groupby(["cls", "lf_bin", "year"])["hri"].quantile(TARGET_PCTL / 100).rename("hri_target").reset_index()
    p = p.drop(columns=[c for c in ["hri_target"] if c in p.columns]).merge(t, on=["cls", "lf_bin", "year"], how="left")
    p["hr_target"] = p["hr_ref"] / p["hri_target"]
    ex = p["netgen"] * 1000 * (p["hr_corr"] - p["hr_target"]) / 1e6
    p["excess_mmbtu"] = np.where(p["scoreable"], ex.clip(lower=0), np.nan)
    p["waste_usd"] = p["excess_mmbtu"] * p["gas_cost_final"]
    # maintenance can only restore a unit to its own best, not to a better peer's design: cap the recoverable
    # base at the excess over the own-best heat rate (HR_ref / eta_own)
    ex_own = (p["netgen"] * 1000 * (p["hr_corr"] - p["hr_ref"] / p["eta_own"]) / 1e6).clip(lower=0)
    p["excess_own_mmbtu"] = np.where(p["scoreable"], ex_own, np.nan)
    base = np.fmin(p["excess_mmbtu"], p["excess_own_mmbtu"])
    p["recoverable_mmbtu"] = base * p["recovery"]
    p["recoverable_usd"] = p["recoverable_mmbtu"] * p["gas_cost_final"]
    p["deficit_pct"] = np.where(p["scoreable"], (1 - p["hri_own"]).clip(lower=0) * 100, np.nan)
    return p


def cost_table():
    return pd.read_csv(COST_TABLE)


def payback(summary):
    """summary: one row per plant x class with dominant recoverable signature, n_units, unit_size_mw,
    recoverable_usd_per_yr. Adds remediation_cost_usd and payback_yr."""
    ct = cost_table().set_index("signature")
    sig = summary["dominant_recoverable"]
    fixed = sig.map(ct["fixed_usd_per_unit"]).fillna(0)
    per_mw = sig.map(ct["usd_per_mw_of_unit"]).fillna(0)
    summary["remediation_cost_usd"] = summary["n_units"].fillna(1) * (fixed + per_mw * summary["unit_size_mw"].fillna(0))
    with np.errstate(divide="ignore", invalid="ignore"):
        summary["payback_yr"] = np.where(summary["recoverable_usd_per_yr"] > 0,
                                         summary["remediation_cost_usd"] / summary["recoverable_usd_per_yr"], np.nan)
    summary["cost_status"] = "UNVALIDATED placeholder"
    return summary


def scale_check(p):
    """Spec cross-check: 5% compressor efficiency drop on a 100 MW turbine ~ $1.2M/yr. Scale each fouling
    plant-year's waste to 100 MW nameplate and a 5% deficit and compare the median."""
    f = p[p["signature"] == "FOULING"]
    py = f.groupby(["plant_id", "cls", "year"]).agg(w=("waste_usd", "sum"), mw=("nameplate_mw", "first"),
                                                     d=("deficit_pct", "mean"), n=("waste_usd", "size"))
    py = py[(py["d"] > 0.5) & (py["mw"] > 0)]
    scaled = py["w"] * (12 / py["n"]) * (100 / py["mw"]) * (5 / py["d"])
    return scaled.median()
