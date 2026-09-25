"""EIA-860 3_4 Energy Storage, all vintages 2019-2025: time-varying E_rated per plant-year (augmentation-aware),
power ratings, chemistry, enclosure, applications, coupling. Plus plant location (2___Plant)."""
import numpy as np
import pandas as pd
from config import X, CACHE, YEARS

APPS = ["Arbitrage", "Frequency Regulation", "Load Following", "Ramping / Spinning Reserve",
        "Co-Located Renewable Firming", "Transmission and Distribution Deferral", "System Peak Shaving",
        "Load Management", "Voltage or Reactive Power Support", "Backup Power", "Excess Wind and Solar Generation"]
COUPLING = ["AC Coupled", "DC Coupled", "DC Tightly Coupled", "Independent", "Direct Support of Another Unit"]


def _mode(x):
    m = x.dropna().mode()
    return m.iat[0] if len(m) else None


def _read(path, sheet):
    d = pd.read_excel(path, sheet_name=sheet, header=1)
    d.columns = [str(c).strip() for c in d.columns]
    return d[pd.to_numeric(d["Plant Code"], errors="coerce").notna()].copy()


def generators(force=False):
    f = CACHE / "eia860_storage_gens.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    parts = []
    for y in YEARS:
        p = X / f"eia860{y}" / f"3_4_Energy_Storage_Y{y}.xlsx"
        op = _read(p, "Operable")
        op["retire_year"] = np.nan
        rt = _read(p, "Retired and Canceled")
        rc = [c for c in rt.columns if c.startswith("Retirement Year")]
        rt["retire_year"] = pd.to_numeric(rt[rc[0]], errors="coerce") if rc else np.nan
        rt = rt[rt["retire_year"] == y]
        g = pd.concat([op, rt], ignore_index=True)
        g["vintage"] = y
        parts.append(g)
    g = pd.concat(parts, ignore_index=True)
    keep = ["Plant Code", "Generator ID", "Status", "Technology", "Prime Mover", "Nameplate Capacity (MW)",
            "Summer Capacity (MW)", "Operating Month", "Operating Year", "Nameplate Energy Capacity (MWh)",
            "Maximum Charge Rate (MW)", "Maximum Discharge Rate (MW)", "Storage Technology 1", "Storage Technology 2",
            "Storage Enclosure Type", "Utility Name", "retire_year", "vintage"] + APPS + COUPLING
    g = g[[c for c in keep if c in g.columns]].rename(columns={
        "Plant Code": "plant_id", "Generator ID": "gen_id", "Status": "status", "Technology": "technology",
        "Prime Mover": "pm", "Nameplate Capacity (MW)": "nameplate_mw", "Summer Capacity (MW)": "summer_mw",
        "Operating Month": "op_month", "Operating Year": "op_year", "Nameplate Energy Capacity (MWh)": "e_mwh",
        "Maximum Charge Rate (MW)": "max_charge_mw", "Maximum Discharge Rate (MW)": "max_discharge_mw",
        "Storage Technology 1": "chem1", "Storage Technology 2": "chem2", "Storage Enclosure Type": "enclosure",
        "Utility Name": "utility_name"})
    g["plant_id"] = g["plant_id"].astype(int)
    for c in ["nameplate_mw", "summer_mw", "op_month", "op_year", "e_mwh", "max_charge_mw", "max_discharge_mw"]:
        g[c] = pd.to_numeric(g[c], errors="coerce")
    for c in ["gen_id", "status", "technology", "pm", "chem1", "chem2", "enclosure", "utility_name"] + \
            [c for c in APPS + COUPLING if c in g.columns]:
        g[c] = g[c].astype(str).str.strip()
    g.to_parquet(f, index=False)
    return g


def plant_year(force=False):
    """plant x year (BA prime mover): E_rated, MW, charge/discharge ratings, duration, attributes."""
    f = CACHE / "eia860_storage_plant_year.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    g = generators(force)
    g = g[g["pm"] == "BA"].copy()
    yes = lambda s: (s == "Y")
    agg = g.groupby(["plant_id", "vintage"]).agg(
        e_rated_mwh=("e_mwh", "sum"), nameplate_mw=("nameplate_mw", "sum"),
        max_charge_mw=("max_charge_mw", "sum"), max_discharge_mw=("max_discharge_mw", "sum"),
        n_gens=("gen_id", "nunique"), op_year_min=("op_year", "min"),
        op_month_first=("op_month", "first"),
        chem=("chem1", _mode), enclosure=("enclosure", _mode),
        utility_name=("utility_name", "first"))
    agg["np_x_yr"] = g.assign(w=g["nameplate_mw"] * g["op_year"]).groupby(["plant_id", "vintage"])["w"].sum()
    agg["cod_year"] = agg.pop("np_x_yr") / agg["nameplate_mw"].where(agg["nameplate_mw"] > 0)
    for c in APPS + COUPLING:
        if c in g.columns:
            agg[c] = g.groupby(["plant_id", "vintage"])[c].agg(lambda s: "Y" if yes(s).any() else "N")
    agg = agg.reset_index().rename(columns={"vintage": "year"})
    agg["duration_h"] = agg["e_rated_mwh"] / agg["nameplate_mw"].where(agg["nameplate_mw"] > 0)
    agg.to_parquet(f, index=False)
    return agg


def plants(force=False):
    f = CACHE / "eia860_plants_bess.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    parts = []
    for y in YEARS:
        d = pd.read_excel(X / f"eia860{y}" / f"2___Plant_Y{y}.xlsx", header=1)
        d.columns = [str(c).strip() for c in d.columns]
        d = d[pd.to_numeric(d["Plant Code"], errors="coerce").notna()]
        d = d[["Plant Code", "State", "County", "Latitude", "Longitude", "Balancing Authority Code", "Utility Name"]].copy()
        d["vintage"] = y
        parts.append(d)
    d = pd.concat(parts).sort_values("vintage").drop_duplicates("Plant Code", keep="last")
    d.columns = ["plant_id", "state_860", "county", "lat", "lon", "ba_860", "operator_860", "vintage"]
    d["plant_id"] = d["plant_id"].astype(int)
    for c in ["lat", "lon"]:
        d[c] = pd.to_numeric(d[c], errors="coerce")
    for c in ["state_860", "county", "ba_860", "operator_860"]:
        d[c] = d[c].astype(str).str.strip()
    d.to_parquet(f, index=False)
    return d


def owners():
    y = YEARS[-1]
    d = pd.read_excel(X / f"eia860{y}" / f"4___Owner_Y{y}.xlsx", header=1)
    d.columns = [str(c).strip() for c in d.columns]
    d = d[pd.to_numeric(d["Plant Code"], errors="coerce").notna()]
    d["Percent Owned"] = pd.to_numeric(d["Percent Owned"], errors="coerce")
    s = d.groupby(["Plant Code", "Owner Name"])["Percent Owned"].sum().reset_index()
    s = s.sort_values("Percent Owned").drop_duplicates("Plant Code", keep="last")
    s.columns = ["plant_id", "owner_sched4", "owner_pct"]
    s["plant_id"] = s["plant_id"].astype(int)
    return s


if __name__ == "__main__":
    py = plant_year(force=True)
    plants(force=True)
    t = py.groupby("year").agg(gw=("nameplate_mw", "sum"), gwh=("e_rated_mwh", "sum"), n=("plant_id", "size"))
    t["gw"] /= 1e3; t["gwh"] /= 1e3
    print(t.round(1))
    print("median duration 2025:", py[py.year == 2025].duration_h.median().round(2),
          "MW-weighted:", (py[py.year == 2025].e_rated_mwh.sum() / py[py.year == 2025].nameplate_mw.sum()).round(2))
    print(py[py.year == 2025].chem.value_counts().head(6)); print(py[py.year == 2025].enclosure.value_counts().head(6))
