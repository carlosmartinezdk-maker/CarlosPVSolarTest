"""Climate / environment region per plant: coastal > arid > industrial > inland (fouling is environment-driven).
coastal: within COAST_KM of the Natural Earth 1:50m land outline (ocean coast; Great Lakes are not coast here)
arid: county mean annual precipitation 2019-2025 below ARID_MM (nClimGrid county)
industrial: EIA-860 sector is industrial or commercial (on-site / host facility)."""
import glob
import json
import numpy as np
import pandas as pd
from config import RAW, CACHE
from weather import plant_county_codes

COAST_KM = 30.0
ARID_MM = 400.0


def _coast_points():
    d = json.load(open(RAW / "land-50m.json"))
    sx, sy = d["transform"]["scale"]
    tx, ty = d["transform"]["translate"]
    pts = []
    for arc in d["arcs"]:
        a = np.cumsum(np.array(arc, dtype=float), axis=0)
        lon, lat = a[:, 0] * sx + tx, a[:, 1] * sy + ty
        m = (lon > -170) & (lon < -60) & (lat > 15) & (lat < 72)
        pts.append(np.c_[lat[m], lon[m]])
    return np.vstack(pts)


def _county_precip():
    path = sorted(glob.glob(str(RAW / "climdiv-pcpncy-*")))[-1]
    rows = []
    with open(path) as fh:
        for line in fh:
            yr = int(line[7:11])
            if 2019 <= yr <= 2025:
                v = [float(x) for x in line[11:].split()]
                if all(x > -9 for x in v):
                    rows.append((int(line[0:2]), int(line[2:5]), sum(v) * 25.4))
    d = pd.DataFrame(rows, columns=["ncdc_state", "county_fips", "mm"])
    return d.groupby(["ncdc_state", "county_fips"])["mm"].mean().rename("precip_mm").reset_index()


def regions():
    f = CACHE / "climate_regions.parquet"
    if f.exists():
        return pd.read_parquet(f)
    p = plant_county_codes()
    p = p.merge(_county_precip(), on=["ncdc_state", "county_fips"], how="left")
    c = _coast_points()
    la1, lo1 = np.radians(p["lat"].fillna(0).values), np.radians(p["lon"].fillna(0).values)
    dmin = np.full(len(p), np.inf)
    cl, co = np.radians(c[:, 0]), np.radians(c[:, 1])
    for i in range(0, len(p), 500):
        a = np.sin((cl[None, :] - la1[i:i + 500, None]) / 2) ** 2 + np.cos(la1[i:i + 500, None]) * np.cos(cl[None, :]) \
            * np.sin((co[None, :] - lo1[i:i + 500, None]) / 2) ** 2
        dmin[i:i + 500] = (6371 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))).min(1)
    p["coast_km"] = np.where(p["lat"].notna(), dmin, np.nan)
    ind = p["sector"].str.contains("Industrial|Commercial", case=False, na=False)
    p["climate_region"] = np.select([p["coast_km"] <= COAST_KM, p["precip_mm"] < ARID_MM, ind],
                                    ["coastal", "arid", "industrial"], default="inland")
    out = p[["plant_id", "coast_km", "precip_mm", "climate_region"]]
    out.to_parquet(f, index=False)
    return out


if __name__ == "__main__":
    r = regions()
    print(r["climate_region"].value_counts())
