"""Hybrid (co-located) quarantine. A site is a hybrid if ANY of:
  - apparent RTE > 1.0 in any month with meaningful charge (charging from the host generator is unreported)
  - EIA-860 Co-Located Renewable Firming == Y (any vintage), or DC Coupled / DC Tightly Coupled == Y
  - the same Plant Id reports PV generation on Page 1 Generation and Fuel Data (any year)
Hybrids are a separate cohort and never enter fleet efficiency statistics."""
import numpy as np
import pandas as pd
from config import CACHE

RTE_IMPOSSIBLE = 1.0
MIN_CHARGE_FOR_RTE_TEST = 1.0     # MWh


def flags(panel, py):
    pv = pd.read_parquet(CACHE / "eia923_page1_long.parquet", columns=["plant_id", "pm", "netgen"])
    pv_plants = set(pv.loc[(pv["pm"] == "PV") & (pv["netgen"].fillna(0) != 0), "plant_id"]) | \
        set(pv.loc[pv["pm"] == "PV", "plant_id"])
    f = panel.groupby("plant_id").apply(lambda d: bool(((d["charge"] >= MIN_CHARGE_FOR_RTE_TEST)
                                                        & (d["discharge"] / d["charge"] > RTE_IMPOSSIBLE)).any()),
                                        include_groups=False).rename("rte_gt_1")
    f = f.to_frame()
    cols = [c for c in ["Co-Located Renewable Firming", "DC Coupled", "DC Tightly Coupled"] if c in py.columns]
    a = py.groupby("plant_id")[cols].agg(lambda s: (s == "Y").any())
    f = f.join(a, how="left").fillna(False)
    f["pv_same_plant"] = f.index.isin(pv_plants)
    f = f.rename(columns={"Co-Located Renewable Firming": "colocated_firming", "DC Coupled": "dc_coupled",
                          "DC Tightly Coupled": "dc_tight"})
    rule_cols = ["rte_gt_1", "colocated_firming", "pv_same_plant"] + [c for c in ["dc_coupled", "dc_tight"] if c in f]
    f["hybrid"] = f[rule_cols].any(axis=1)
    f["hybrid_reasons"] = f[rule_cols].apply(lambda r: ",".join(c for c in rule_cols if r[c]), axis=1)
    return f.reset_index()
