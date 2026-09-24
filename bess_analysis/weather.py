"""Monthly ambient per site from NOAA nClimGrid county monthly mean (same method as gas_analysis/weather.py).
Unmatched counties borrow the nearest matched site's county within 150 km. degF -> degC."""
import glob
import re
import numpy as np
import pandas as pd
from config import RAW, CACHE, YEARS
from load_860_allvintages import plants

NCDC_STATE = {s: i + 1 for i, s in enumerate(
    "AL AZ AR CA CO CT DE FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA "
    "RI SC SD TN TX UT VT VA WA WV WI WY".split())}
NCDC_STATE.update({"HI": 49, "AK": 50})
MAX_NEAREST_KM = 150.0


def _norm(s):
    s = str(s).lower().replace("saint", "st").replace("st.", "st").replace("ste.", "ste")
    s = re.sub(r"\b(county|parish|borough|census area|city and borough|municipality|municipio|planning region)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def county_temps():
    f = CACHE / "nclimgrid_county_monthly.parquet"
    if f.exists():
        return pd.read_parquet(f)
    rows = []
    with open(sorted(glob.glob(str(RAW / "climdiv-tmpccy-*")))[-1]) as fh:
        for line in fh:
            yr = int(line[7:11])
            if YEARS[0] <= yr <= YEARS[-1]:
                for m, v in enumerate(line[11:].split(), 1):
                    v = float(v)
                    if v > -99:
                        rows.append((int(line[0:2]), int(line[2:5]), yr, m, (v - 32) * 5 / 9))
    d = pd.DataFrame(rows, columns=["ncdc_state", "county_fips", "year", "month", "t_amb_c"])
    d.to_parquet(f, index=False)
    return d


def plant_monthly_temps(plant_ids):
    p = plants()
    p = p[p["plant_id"].isin(plant_ids)].copy()
    cty = pd.read_csv(RAW / "national_county2020.txt", sep="|", dtype=str)
    lut = dict(zip(cty["STATE"] + "|" + cty["COUNTYNAME"].map(_norm), cty["COUNTYFP"].astype(int)))
    p["county_fips"] = (p["state_860"] + "|" + p["county"].map(_norm)).map(lut)
    p["ncdc_state"] = p["state_860"].map(NCDC_STATE)
    ct = county_temps()
    have = set(zip(ct["ncdc_state"], ct["county_fips"]))
    p["ok"] = [(s, c) in have for s, c in zip(p["ncdc_state"], p["county_fips"])]
    p["src_state"], p["src_fips"] = p["ncdc_state"], p["county_fips"]
    p["t_source"] = np.where(p["ok"], "county", None)
    good, bad = p[p["ok"] & p["lat"].notna()], p[~p["ok"] & p["lat"].notna()]
    if len(bad) and len(good):
        la1, lo1 = np.radians(bad["lat"].values)[:, None], np.radians(bad["lon"].values)[:, None]
        la2, lo2 = np.radians(good["lat"].values)[None, :], np.radians(good["lon"].values)[None, :]
        a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
        km = 6371 * 2 * np.arcsin(np.sqrt(a))
        j, use = km.argmin(1), km.min(1) <= MAX_NEAREST_KM
        idx = bad.index[use]
        p.loc[idx, "src_state"] = good["ncdc_state"].values[j[use]]
        p.loc[idx, "src_fips"] = good["county_fips"].values[j[use]]
        p.loc[idx, "t_source"] = "nearest_county"
    p = p[p["t_source"].notna()]
    out = p[["plant_id", "src_state", "src_fips", "t_source"]].merge(
        ct, left_on=["src_state", "src_fips"], right_on=["ncdc_state", "county_fips"])
    return out[["plant_id", "year", "month", "t_amb_c", "t_source"]]
