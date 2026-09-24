"""Monthly ambient dry-bulb per plant from NOAA nClimGrid county monthly (climdiv-tmpccy).

NSRDB PSM3 needs an API key not available here; the spec's fallback (nClimGrid by county) is used.
Plants whose county cannot be matched take the nearest matched plant's county series (flagged).
Values are converted from degF to degC.
"""
import glob
import re
import numpy as np
import pandas as pd
from config import RAW, CACHE, YEARS
from load_860_allvintages import plants

# NCDC climdiv state numbering (alphabetical, CONUS 01-48, 49 HI, 50 AK)
NCDC_STATE = {s: i + 1 for i, s in enumerate(
    "AL AZ AR CA CO CT DE FL GA ID IL IN IA KS KY LA ME MD MA MI MN MS MO MT NE NV NH NJ NM NY NC ND OH OK OR PA "
    "RI SC SD TN TX UT VT VA WA WV WI WY".split())}
NCDC_STATE.update({"HI": 49, "AK": 50})
MAX_NEAREST_KM = 150.0   # beyond this a borrowed county series is not credible -> T_amb missing


def _norm(s):
    s = str(s).lower().replace("saint", "st").replace("st.", "st").replace("ste.", "ste")
    s = re.sub(r"\b(county|parish|borough|census area|city and borough|municipality|municipio|planning region)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def county_temps():
    f = CACHE / "nclimgrid_county_monthly.parquet"
    if f.exists():
        return pd.read_parquet(f)
    path = sorted(glob.glob(str(RAW / "climdiv-tmpccy-*")))[-1]
    rows = []
    with open(path) as fh:
        for line in fh:
            yr = int(line[7:11])
            if yr < YEARS[0] or yr > YEARS[-1]:
                continue
            vals = [float(v) for v in line[11:].split()]
            for m, v in enumerate(vals, 1):
                if v > -99:
                    rows.append((int(line[0:2]), int(line[2:5]), yr, m, (v - 32) * 5 / 9))
    d = pd.DataFrame(rows, columns=["ncdc_state", "county_fips", "year", "month", "t_amb_c"])
    d.to_parquet(f, index=False)
    return d


def plant_county_codes():
    p = plants()
    cty = pd.read_csv(RAW / "national_county2020.txt", sep="|", dtype=str)
    cty["key"] = cty["STATE"] + "|" + cty["COUNTYNAME"].map(_norm)
    lut = dict(zip(cty["key"], cty["COUNTYFP"].astype(int)))
    p["key"] = p["state_860"] + "|" + p["county"].map(_norm)
    p["county_fips"] = p["key"].map(lut)
    p["ncdc_state"] = p["state_860"].map(NCDC_STATE)
    return p


def plant_monthly_temps(plant_ids):
    """Returns plant_id x year x month -> t_amb_c, t_source ('county' | 'nearest_county' | missing)."""
    p = plant_county_codes()
    ct = county_temps()
    have = set(zip(ct["ncdc_state"], ct["county_fips"]))
    p["ok"] = [(s, c) in have for s, c in zip(p["ncdc_state"], p["county_fips"])]
    p = p[p["plant_id"].isin(plant_ids)].copy()
    good = p[p["ok"] & p["lat"].notna()]
    p["src_state"], p["src_fips"], p["t_source"] = p["ncdc_state"], p["county_fips"], np.where(p["ok"], "county", None)
    bad = p[~p["ok"] & p["lat"].notna()]
    if len(bad) and len(good):
        la1, lo1 = np.radians(bad["lat"].values)[:, None], np.radians(bad["lon"].values)[:, None]
        la2, lo2 = np.radians(good["lat"].values)[None, :], np.radians(good["lon"].values)[None, :]
        a = np.sin((la2 - la1) / 2) ** 2 + np.cos(la1) * np.cos(la2) * np.sin((lo2 - lo1) / 2) ** 2
        km = 6371 * 2 * np.arcsin(np.sqrt(a))
        j, dmin = km.argmin(1), km.min(1)
        use = dmin <= MAX_NEAREST_KM
        idx = bad.index[use]
        p.loc[idx, "src_state"] = good["ncdc_state"].values[j[use]]
        p.loc[idx, "src_fips"] = good["county_fips"].values[j[use]]
        p.loc[idx, "t_source"] = "nearest_county"
    p = p[p["t_source"].notna()]
    out = p[["plant_id", "src_state", "src_fips", "t_source"]].merge(
        ct, left_on=["src_state", "src_fips"], right_on=["ncdc_state", "county_fips"])
    return out[["plant_id", "year", "month", "t_amb_c", "t_source"]]


if __name__ == "__main__":
    p = plant_county_codes()
    print("county match rate (all 860 plants):", p["county_fips"].notna().mean().round(3))
    print(p.loc[p["county_fips"].isna(), ["state_860", "county"]].value_counts().head(20))
