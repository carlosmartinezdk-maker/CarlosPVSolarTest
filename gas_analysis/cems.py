"""EPA CAMPD hourly CEMS (Part 75) -> unit-year cycling / trip / ramp metrics for the balance-of-plant layer.

Bulk state-year files are streamed one at a time and reduced to one row per unit-year, then deleted.
Definitions (spec, OPTIONAL UPLIFT):
  start      = GLOAD == 0 for >=1 h, then GLOAD > 5% of unit max sustained >=2 h
  trip       = GLOAD > 40% of unit max in hour t-1 and GLOAD == 0 in hour t (no ramp-down)
  cold/warm/hot start = offline >48 h / 8-48 h / <8 h before the start
  ramp_p95   = 95th percentile of |dGLOAD| between consecutive operating hours (MW; normalised by EIA MW later)
  op_hours   = hours with GLOAD > 0
Facility ID is the ORIS code = EIA plant id.
"""
import sys
import subprocess
import numpy as np
import pandas as pd
from config import RAW, CACHE

BASE = "https://api.epa.gov/easey/bulk-files/emissions/hourly/state/emissions-hourly-{y}-{s}.csv"
STATES = ("al ak az ar ca co ct de dc fl ga hi id il in ia ks ky la me md ma mi mn ms mo mt ne nv nh nj nm ny nc nd "
          "oh ok or pa ri sc sd tn tx ut vt va wa wv wi wy pr").split()
START_LOAD = 0.05
START_SUSTAIN_H = 2
TRIP_FROM = 0.40
COLD_H, WARM_H = 48, 8
COLS = ["Facility ID", "Unit ID", "Date", "Hour", "Gross Load (MW)", "Heat Input (mmBtu)", "Primary Fuel Type", "Unit Type"]


def unit_metrics(d):
    gl = d["Gross Load (MW)"].fillna(0).to_numpy(float)
    mx = gl.max()
    n = len(gl)
    on = gl > 0
    out = {"max_load_mw": mx, "op_hours": int(on.sum()), "hours": n,
           "heat_input_mmbtu": float(d["Heat Input (mmBtu)"].fillna(0).sum())}
    if mx <= 0:
        return {**out, "starts": 0, "trips": 0, "cold": 0, "warm": 0, "hot": 0, "ramp_p95_mw": 0.0}
    # starts: off->on transitions with >=2 h above 5% of max
    trans = np.where(~on[:-1] & on[1:])[0] + 1
    above = gl > START_LOAD * mx
    starts = [t for t in trans if t + START_SUSTAIN_H <= n and above[t:t + START_SUSTAIN_H].all()]
    # offline duration before each start
    off_run = np.zeros(n, int)
    c = 0
    for i in range(n):
        c = c + 1 if not on[i] else 0
        off_run[i] = c
    dur = np.array([off_run[t - 1] for t in starts]) if starts else np.array([])
    trips = int(((gl[1:] == 0) & (gl[:-1] > TRIP_FROM * mx)).sum())
    dg = np.abs(np.diff(gl))[on[1:] & on[:-1]]
    return {**out, "starts": len(starts), "trips": trips, "cold": int((dur > COLD_H).sum()),
            "warm": int(((dur >= WARM_H) & (dur <= COLD_H)).sum()), "hot": int((dur < WARM_H).sum()),
            "ramp_p95_mw": float(np.percentile(dg, 95)) if len(dg) else 0.0}


def process(year, state, tmp):
    url = BASE.format(y=year, s=state)
    r = subprocess.run(["curl", "-sS", "-m", "1800", "--retry", "4", "--retry-delay", "5", "-f", "-o", str(tmp), url])
    if r.returncode != 0:
        return pd.DataFrame()
    d = pd.read_csv(tmp, usecols=COLS, low_memory=False)
    tmp.unlink()
    d = d.sort_values(["Facility ID", "Unit ID", "Date", "Hour"])
    rows = []
    for (fid, uid), u in d.groupby(["Facility ID", "Unit ID"], sort=False):
        m = unit_metrics(u)
        m.update({"plant_id": int(fid), "unit_id": str(uid), "year": year, "state": state.upper(),
                  "unit_type": u["Unit Type"].mode().iat[0] if u["Unit Type"].notna().any() else "",
                  "primary_fuel": u["Primary Fuel Type"].mode().iat[0] if u["Primary Fuel Type"].notna().any() else ""})
        rows.append(m)
    return pd.DataFrame(rows)


def main(years):
    outdir = CACHE / "cems"
    outdir.mkdir(exist_ok=True)
    tmp = RAW / "cems_tmp.csv"
    for y in years:
        for s in STATES:
            f = outdir / f"units_{y}_{s}.parquet"
            if f.exists():
                continue
            df = process(y, s, tmp)
            df.to_parquet(f, index=False)
            print(y, s, len(df), flush=True)


def load():
    fs = sorted((CACHE / "cems").glob("units_*.parquet"))
    return pd.concat([pd.read_parquet(f) for f in fs], ignore_index=True) if fs else pd.DataFrame()


if __name__ == "__main__":
    main([int(a) for a in sys.argv[1:]] or [2024, 2025])
