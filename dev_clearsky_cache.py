"""
DEV/TEST ONLY - NOT PART OF THE S2 CONTRACT.

s2_nsrdb.py (the real pipeline stage) is a standalone batch job that pulls
ONLY real NSRDB Track A data and has no fallback concept at all, per the
brief. This module exists so the rest of the repo can be built and tested
offline, in this sandbox, while developer.nlr.gov is unreachable from it.
It writes clear-sky (pvlib Ineichen) weather to the SAME cache directory
S2 uses, but as `weather_B.parquet` (never `weather_A.parquet`, so it can
never be mistaken for real NSRDB data by a downstream stage's cache check).

Every PI/PRI/fault/dollar number computed against a weather_B.parquet file
is a stopgap, not decision-grade - S3 tags every such row
weather_track="B_clearsky_stopgap" so this is never silently indistinguishable
from a real Track A run downstream.

DELETE THIS FILE'S OUTPUT (or the whole nsrdb_cache/) before running the
real pipeline against a real S2 pull, or run s2_nsrdb.py's real pull first -
S3 always prefers weather_A.parquet where both exist.
"""
import logging
import os

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s DEV-CLEARSKY %(message)s")
log = logging.getLogger("dev_clearsky")

GRID_DEG = 0.04
CALENDAR_HOURS = {2019: 8760, 2020: 8784, 2021: 8760, 2022: 8760, 2023: 8760,
                  2024: 8784, 2025: 8760}
CALENDAR_HOURS_2026_YTD = 3624


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat / GRID_DEG) * GRID_DEG, round(lon / GRID_DEG) * GRID_DEG)


def cache_path_b(cache_dir: str, grid_lat: float, grid_lon: float, year: int) -> str:
    return os.path.join(cache_dir, f"grid_lat={grid_lat}", f"grid_lon={grid_lon}",
                        f"year={year}", "weather_B.parquet")


def local_standard_utc_offset_hours(lat: float, lon: float) -> float:
    from timezonefinder import TimezoneFinder
    from zoneinfo import ZoneInfo
    tf = TimezoneFinder()
    tzname = tf.timezone_at(lat=lat, lng=lon) or "Etc/UTC"
    jan15 = pd.Timestamp("2025-01-15 12:00", tz=ZoneInfo(tzname))
    return jan15.utcoffset().total_seconds() / 3600.0


def clearsky_year(lat: float, lon: float, year: int) -> pd.DataFrame:
    from zoneinfo import ZoneInfo
    from pvlib.location import Location

    offset_hr = int(round(local_standard_utc_offset_hours(lat, lon)))
    fixed_tz = ZoneInfo(f"Etc/GMT{-offset_hr:+d}")
    loc = Location(lat, lon, tz=fixed_tz)

    n_hours = CALENDAR_HOURS.get(year, CALENDAR_HOURS_2026_YTD)
    times_local = pd.date_range(f"{year}-01-01 00:30", periods=n_hours, freq="h", tz=fixed_tz)

    cs = loc.get_clearsky(times_local, model="ineichen")
    df = pd.DataFrame({
        "ghi": cs["ghi"], "dni": cs["dni"], "dhi": cs["dhi"],
        "air_temperature": 20.0 + 10.0 * np.sin(2 * np.pi * (times_local.dayofyear - 80) / 365.25),
        "wind_speed": 3.0,
        "surface_albedo": 0.2,
    }, index=times_local)
    df.index.name = "time"
    return df


def ensure_cell_year(cache_dir: str, grid_lat: float, grid_lon: float, year: int) -> str:
    path = cache_path_b(cache_dir, grid_lat, grid_lon, year)
    if not os.path.exists(path):
        df = clearsky_year(grid_lat, grid_lon, year)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        df.to_parquet(path)
    return path


def main(sites_lat_lon: list[tuple[float, float]], years: list[int], cache_dir: str):
    cells = sorted(set(grid_cell(lat, lon) for lat, lon in sites_lat_lon))
    log(f"{len(sites_lat_lon)} sites -> {len(cells)} unique grid cells")
    for i, (lat, lon) in enumerate(cells):
        for year in years:
            ensure_cell_year(cache_dir, lat, lon, year)
        if (i + 1) % 20 == 0 or i == len(cells) - 1:
            log(f"progress: {i+1}/{len(cells)} cells")
    log("done")


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sites-csv", required=True)
    ap.add_argument("--years", default="2019-2025")
    ap.add_argument("--cache-dir", default="nsrdb_cache")
    args = ap.parse_args()

    import csv
    with open(args.sites_csv) as f:
        rows = [(float(r["lat"]), float(r["lon"])) for r in csv.DictReader(f)]

    if "-" in args.years:
        lo, hi = args.years.split("-")
        years = list(range(int(lo), int(hi) + 1))
    else:
        years = [int(y) for y in args.years.split(",")]

    main(rows, years, args.cache_dir)
