"""EIA-923 'Page 1 Energy Storage': monthly charge (Quantity) and discharge (Grossgen) per plant, BA / MWH only."""
import glob
import pandas as pd
from config import X, CACHE, YEARS, MONTHS

SHEET = "Page 1 Energy Storage"
PM_BATTERY = "BA"
FUEL_BATTERY = "MWH"


def _find_header(path, sheet):
    raw = pd.read_excel(path, sheet_name=sheet, header=None, nrows=10)
    for i, row in raw.iterrows():
        if any(str(v).strip() == "Plant Id" for v in row.values):
            return i
    raise ValueError(f"no 'Plant Id' in first 10 rows of {path}:{sheet}")


def load_year(year):
    path = sorted(glob.glob(str(X / f"f923_{year}" / "EIA923_Schedules_2_3_4_5_M_12_*.xlsx")))[0]
    d = pd.read_excel(path, sheet_name=SHEET, header=_find_header(path, SHEET))
    d.columns = [str(c).replace("\n", " ").strip() for c in d.columns]
    d = d[pd.to_numeric(d["Plant Id"], errors="coerce").notna()].copy()
    d["pm"] = d["Reported Prime Mover"].astype(str).str.strip()
    d["fuel"] = d["Reported Fuel Type Code"].astype(str).str.strip()
    parts = []
    ids = {"Plant Id": "plant_id", "Plant Name": "plant_name", "Operator Name": "operator", "Plant State": "state",
           "NERC Region": "nerc", "Balancing Authority Code": "ba", "Respondent Frequency": "resp_freq",
           "Sector Name": "sector"}
    for mi, m in enumerate(MONTHS, 1):
        p = d[list(ids) + ["pm", "fuel", f"Quantity {m}", f"Grossgen {m}", f"Netgen {m}"]].rename(
            columns={**ids, f"Quantity {m}": "charge", f"Grossgen {m}": "discharge", f"Netgen {m}": "netgen"})
        p["month"] = mi
        parts.append(p)
    out = pd.concat(parts, ignore_index=True)
    out["year"] = year
    for c in ["charge", "discharge", "netgen"]:
        out[c] = pd.to_numeric(out[c], errors="coerce")
    for c in ["plant_name", "operator", "state", "nerc", "ba", "resp_freq", "sector"]:
        out[c] = out[c].astype(str).str.strip()
    out["plant_id"] = out["plant_id"].astype(int)
    return out


def load_all(force=False):
    f = CACHE / "eia923_storage_long.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f)
    d = pd.concat([load_year(y) for y in YEARS], ignore_index=True)
    d.to_parquet(f, index=False)
    return d


def battery_monthly(force=False):
    """plant x year x month charge / discharge for lithium-type batteries (PM BA, fuel MWH)."""
    d = load_all(force)
    b = d[(d["pm"] == PM_BATTERY) & (d["fuel"] == FUEL_BATTERY)]
    keys = ["plant_id", "year", "month"]
    num = b.groupby(keys)[["charge", "discharge", "netgen"]].sum(min_count=1).reset_index()
    attrs = b.sort_values("year").groupby("plant_id")[["plant_name", "operator", "state", "nerc", "ba", "sector"]].last()
    rf = b.groupby(["plant_id", "year"])["resp_freq"].agg(lambda x: "M" if x.str.contains("M").any() else "A")
    return num.merge(rf.rename("resp_freq").reset_index(), on=["plant_id", "year"]).merge(attrs, on="plant_id")


if __name__ == "__main__":
    load_all(force=True)
    b = battery_monthly()
    d = load_all()
    print(d.groupby(["pm", "fuel"]).size().sort_values().tail(12))
    print((b.groupby("year")[["charge", "discharge"]].sum() / 1e3).round(0), b.groupby("year").plant_id.nunique())
    print(b.groupby("year").resp_freq.value_counts().unstack())
