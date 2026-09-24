"""Plant-month delivered gas cost from the pre-built EIA-923 Page 5 merge (already $/MMBtu -- never divide again)."""
import numpy as np
import pandas as pd
from config import FUEL_COST_CSV

PRICE_MIN, PRICE_MAX = 0.5, 50.0          # $/MMBtu plausibility band; outside -> fall back a tier
HC_MIN, HC_MAX = 0.80, 1.20               # MMBtu/Mcf plausibility for heat content
NATL_CHECK = {2019: 3.09, 2020: 2.66, 2021: 5.36, 2022: 7.30, 2023: 3.89, 2024: 3.05, 2025: 4.07}


def load():
    d = pd.read_csv(FUEL_COST_CSV)
    d["price_qc"] = "ok"
    bad = ~d["gas_cost_final"].between(PRICE_MIN, PRICE_MAX)
    st_ok = d["state_cost"].between(PRICE_MIN, PRICE_MAX)
    m1 = bad & st_ok
    d.loc[m1, "gas_cost_final"] = d.loc[m1, "state_cost"]
    d.loc[m1, "cost_source"] = "state"
    d.loc[m1, "price_qc"] = "implausible->state"
    m2 = ~d["gas_cost_final"].between(PRICE_MIN, PRICE_MAX)
    d.loc[m2, "gas_cost_final"] = d.loc[m2, "natl_cost"]
    d.loc[m2, "cost_source"] = "national"
    d.loc[m2, "price_qc"] = "implausible->national"
    hc = d["heat_content_MMBtu_per_Mcf"]
    d["hc_valid"] = hc.between(HC_MIN, HC_MAX)
    med = d[d["hc_valid"]].groupby("plant_id")["heat_content_MMBtu_per_Mcf"].median().rename("hc_median")
    d = d.merge(med, on="plant_id", how="left")
    d["heat_content_drift"] = np.where(d["hc_valid"], hc / d["hc_median"], np.nan)
    keep = ["plant_id", "year", "month", "gas_cost_final", "cost_source", "price_qc", "heat_content_MMBtu_per_Mcf",
            "heat_content_drift", "firm_delivery_share", "firm_supply_share", "spot_share", "tolling_share",
            "n_suppliers", "natl_cost", "regulated"]
    return d[keep]


def national_check(d=None):
    d = load() if d is None else d
    got = d.groupby("year")["natl_cost"].mean()
    return pd.DataFrame({"expected": pd.Series(NATL_CHECK), "got": got})


if __name__ == "__main__":
    d = load()
    print(d["price_qc"].value_counts())
    print(national_check(d).round(2))
