"""EIA-860 all vintages 2019-2025: time-varying plant x class capacity and attributes."""
import numpy as np
import pandas as pd
from config import X, CACHE, YEARS, PM_CLASS, TECH_CLASS, GAS_FUELS

GEN_COLS = ["Plant Code", "Generator ID", "Technology", "Prime Mover", "Unit Code", "Nameplate Capacity (MW)",
            "Summer Capacity (MW)", "Minimum Load (MW)", "Operating Year", "Operating Month", "Duct Burners",
            "Can Bypass Heat Recovery Steam Generator?", "Energy Source 1", "Utility Name", "Utility ID",
            "Associated with Combined Heat and Power System", "Status"]


def _read(path, sheet):
    df = pd.read_excel(path, sheet_name=sheet, header=1)
    df.columns = [str(c).strip() for c in df.columns]
    return df[pd.to_numeric(df.get("Plant Code"), errors="coerce").notna()]


def generators(year):
    p = X / f"eia860{year}" / f"3_1_Generator_Y{year}.xlsx"
    op = _read(p, "Operable")
    op["retire_year"] = np.nan
    rt = _read(p, "Retired and Canceled")
    rcol = next(c for c in rt.columns if c.startswith("Retirement Year"))
    rt["retire_year"] = pd.to_numeric(rt[rcol], errors="coerce")
    rt = rt[rt["retire_year"] == year]          # retired during the vintage year: operated part of it
    g = pd.concat([op[GEN_COLS + ["retire_year"]], rt[[c for c in GEN_COLS if c in rt.columns] + ["retire_year"]]],
                  ignore_index=True)
    g["vintage"] = year
    return g


def load_generators(force=False):
    f = CACHE / "eia860_generators.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    g = pd.concat([generators(y) for y in YEARS], ignore_index=True)
    g = g.rename(columns={"Plant Code": "plant_id", "Generator ID": "gen_id", "Technology": "technology",
                          "Prime Mover": "pm", "Unit Code": "unit_code", "Nameplate Capacity (MW)": "nameplate_mw",
                          "Summer Capacity (MW)": "summer_mw", "Minimum Load (MW)": "min_load_mw",
                          "Operating Year": "op_year", "Operating Month": "op_month", "Duct Burners": "duct_burners",
                          "Can Bypass Heat Recovery Steam Generator?": "hrsg_bypass", "Energy Source 1": "es1",
                          "Utility Name": "utility_name", "Utility ID": "utility_id",
                          "Associated with Combined Heat and Power System": "chp_860", "Status": "status"})
    g["plant_id"] = g["plant_id"].astype(int)
    for c in ["nameplate_mw", "summer_mw", "min_load_mw", "op_year", "op_month", "utility_id"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    for c in ["gen_id", "technology", "pm", "unit_code", "duct_burners", "hrsg_bypass", "es1", "utility_name",
              "chp_860", "status"]:
        g[c] = g[c].astype(str).str.strip()
    g.to_parquet(f, index=False)
    return g


def gas_capacity(force=False):
    """plant x class x year: nameplate, summer, min load, n units, unit size, COD, duct burners, bypass."""
    f = CACHE / "eia860_gas_capacity.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    g = load_generators(force)
    gas = g["technology"].isin(TECH_CLASS) | g["es1"].isin(GAS_FUELS)
    g = g[gas & g["pm"].isin(PM_CLASS)].copy()
    g["cls"] = g["pm"].map(PM_CLASS)
    g["year"] = g["vintage"]
    # frame-size generators: CT/CS for CC (the gas turbines), everything for the other classes
    g["is_frame"] = np.where(g["cls"] == "CC", g["pm"].isin(["CT", "CS"]), True)
    g["np_x_yr"] = g["nameplate_mw"] * g["op_year"]

    def agg(d):
        fr = d[d["is_frame"]]
        return pd.Series({
            "nameplate_mw": d["nameplate_mw"].sum(),
            "summer_mw": d["summer_mw"].sum(),
            "min_load_mw": d["min_load_mw"].sum(),
            "n_gens": len(d),
            "n_units": max(len(fr), 1),
            "unit_size_mw": (fr["nameplate_mw"].sum() / max(len(fr), 1)) if len(fr) else d["nameplate_mw"].mean(),
            "cod_year": d["np_x_yr"].sum() / d["nameplate_mw"].sum() if d["nameplate_mw"].sum() > 0 else d["op_year"].min(),
            "first_op_year": d["op_year"].min(),
            "first_op_month": d.loc[d["op_year"] == d["op_year"].min(), "op_month"].min(),
            "duct_burners": "Y" if (d["duct_burners"] == "Y").any() else "N",
            "hrsg_bypass": "Y" if (d["hrsg_bypass"] == "Y").any() else "N",
            "chp_860": "Y" if (d["chp_860"] == "Y").any() else "N",
            "gas_tech": d["technology"].isin(TECH_CLASS).any(),
            "technology": d["technology"].mode().iat[0],
            "utility_name": d["utility_name"].mode().iat[0],
            "retire_in_year": d["retire_year"].notna().all(),
        })
    cap = g.groupby(["plant_id", "cls", "year"]).apply(agg, include_groups=False).reset_index()
    cap.to_parquet(f, index=False)
    return cap


def plants(force=False):
    """Plant attributes, latest vintage wins: lat/lon, county, state, NERC, BA."""
    f = CACHE / "eia860_plants.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    parts = []
    for y in YEARS:
        p = X / f"eia860{y}" / f"2___Plant_Y{y}.xlsx"
        d = pd.read_excel(p, header=1)
        d.columns = [str(c).strip() for c in d.columns]
        d = d[pd.to_numeric(d["Plant Code"], errors="coerce").notna()]
        d = d[["Plant Code", "Plant Name", "State", "County", "Latitude", "Longitude", "NERC Region",
               "Balancing Authority Code", "Utility Name", "Regulatory Status", "Sector Name"]].copy()
        d["vintage"] = y
        parts.append(d)
    d = pd.concat(parts).sort_values("vintage").drop_duplicates("Plant Code", keep="last")
    d.columns = ["plant_id", "plant_name_860", "state_860", "county", "lat", "lon", "nerc_860", "ba_860",
                 "operator_860", "regulatory", "sector", "vintage"]
    d["plant_id"] = d["plant_id"].astype(int)
    for c in ["lat", "lon"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in ["plant_name_860", "state_860", "county", "nerc_860", "ba_860", "operator_860", "regulatory", "sector"]:
        d[c] = d[c].astype(str).str.strip()
    d.to_parquet(f, index=False)
    return d


def owners(force=False):
    """Majority owner per plant (Schedule 4 covers only jointly/non-operator owned; fall back to operator)."""
    f = CACHE / "eia860_owners.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    y = YEARS[-1]
    d = pd.read_excel(X / f"eia860{y}" / f"4___Owner_Y{y}.xlsx", header=1)
    d.columns = [str(c).strip() for c in d.columns]
    d = d[pd.to_numeric(d["Plant Code"], errors="coerce").notna()]
    d["Percent Owned"] = pd.to_numeric(d["Percent Owned"], errors="coerce")
    s = d.groupby(["Plant Code", "Owner Name"])["Percent Owned"].sum().reset_index()
    s = s.sort_values("Percent Owned").drop_duplicates("Plant Code", keep="last")
    s.columns = ["plant_id", "owner_sched4", "owner_pct"]
    s["plant_id"] = s["plant_id"].astype(int)
    s.to_parquet(f, index=False)
    return s


if __name__ == "__main__":
    cap = gas_capacity(force=True)
    print(cap.groupby(["year", "cls"]).nameplate_mw.sum().unstack().round(-2) / 1e3)
    print(plants(force=True).shape, owners(force=True).shape)
