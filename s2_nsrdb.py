"""
S2 - Irradiance pull. Track A: NSRDB PSM v4 GOES Aggregated, hand-rolled
against developer.nlr.gov (NREL was renamed the National Laboratory of the
Rockies; the old domain stopped resolving 29 May 2026 with no redirect -
PSM v3.2.2 is also deprecated in favour of v4). Cached to parquet,
deduplicated on a ~4km grid cell, resumable via a manifest.

Hand-rolled with `requests` rather than pvlib's iotools helpers: this
session's installed pvlib (0.15.2) ships get_nsrdb_psm4_aggregated /
_conus / _full_disc, but the exact request parameters below (wkt point
order, utc=false, leap_day=true, single-point CSV endpoint) are easier to
get right and audit directly against the brief's Section 5 table than to
verify against a moving pvlib default.

API KEY: read from NLR_API_KEY (fallback NREL_API_KEY for compatibility),
env var only. NEVER hardcoded, logged, or written to any cache filename,
parquet, or the explorer (acceptance test 29).

TRACK A / TRACK B STATUS (read this before trusting any number downstream):
  This session's network egress policy blocks outbound access to
  developer.nlr.gov (explicit 403 at the egress proxy - confirmed via
  /__agentproxy/status, and independently confirmed as a general block,
  not domain-specific, by testing two unrelated legitimate hosts,
  www.nrel.gov and api.eia.gov, which also 403). NSRDB cannot be reached
  from this environment as currently configured. See README "NSRDB access
  status" for what to change.

  Per the brief ("do NOT fall back to Track B without saying so in
  writing"), this module falls back to a pvlib clear-sky (Ineichen) model
  ONLY when Track A is unreachable, and marks every affected row/site-year
  with weather_track="B_clearsky_stopgap". This is a STOPGAP to keep the
  rest of the pipeline buildable and testable end-to-end; it must be
  re-run against real NSRDB data before any PI/PRI/fault number is treated
  as decision-grade, because Track A's whole premise is that PI is
  absolute against MEASURED weather - clear-sky erases the weather-year
  effect the method exists to measure.
"""
import io
import json
import logging
import os
import time

import numpy as np
import pandas as pd
import requests

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S2 %(message)s")
log = logging.getLogger("s2")

CACHE_DIR = config.NSRDB_CACHE_DIR
MANIFEST_PATH = os.path.join(CACHE_DIR, "manifest.json")

NLR_API_KEY = (os.environ.get(config.NSRDB_API_KEY_ENV_PRIMARY)
               or os.environ.get(config.NSRDB_API_KEY_ENV_FALLBACK) or "")
NLR_EMAIL = os.environ.get("NLR_EMAIL", "carlos.martinez.dk@gmail.com")

_last_request_ts = 0.0


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    g = config.NSRDB_GRID_DEG
    return (round(lat / g) * g, round(lon / g) * g)


def load_manifest() -> dict:
    if os.path.exists(MANIFEST_PATH):
        with open(MANIFEST_PATH) as f:
            return json.load(f)
    return {}


def save_manifest(manifest: dict) -> None:
    os.makedirs(CACHE_DIR, exist_ok=True)
    tmp = MANIFEST_PATH + ".tmp"
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp, MANIFEST_PATH)


def cache_path(grid_lat: float, grid_lon: float, year: int, track: str) -> str:
    return os.path.join(
        CACHE_DIR, f"grid_lat={grid_lat}", f"grid_lon={grid_lon}", f"year={year}",
        f"weather_{track}.parquet"
    )


def probe_track_a_reachable() -> tuple[bool, str]:
    """One cheap, short-timeout probe, never looped/retried against a
    policy-denied host (README rule)."""
    try:
        requests.head(f"https://{config.NSRDB_HOST}/", timeout=5)
        return True, config.NSRDB_HOST
    except requests.exceptions.RequestException as e:
        log.warning("Track A host %s unreachable: %s", config.NSRDB_HOST, e)
    return False, ""


def _rate_limit() -> None:
    global _last_request_ts
    elapsed = time.monotonic() - _last_request_ts
    wait = config.NSRDB_RATE_LIMIT_SECONDS_PER_REQUEST - elapsed
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def pull_track_a_year(lat: float, lon: float, year: int, host: str) -> pd.DataFrame:
    """Hand-rolled GET against the PSM v4 GOES Aggregated CSV endpoint, per
    the brief's Section 5 parameter table exactly: wkt is POINT(lon lat)
    -longitude first-, utc=false and leap_day=true override the API's wrong
    defaults, one year per request."""
    if not NLR_API_KEY:
        raise RuntimeError("no NLR_API_KEY/NREL_API_KEY set - cannot pull Track A")

    _rate_limit()
    url = f"https://{host}{config.NSRDB_ENDPOINT_PATH}"
    params = {
        "api_key": NLR_API_KEY,
        "wkt": f"POINT({lon} {lat})",
        "names": str(year),
        "interval": str(config.NSRDB_INTERVAL_MIN),
        "attributes": ",".join(config.NSRDB_ATTRIBUTES),
        "utc": "false",
        "leap_day": "true",
        "email": NLR_EMAIL,
        "full_name": "Carlos+Martinez",
        "affiliation": "SkySpecs",
        "reason": "PI_PRI_underperformance_analysis",
    }
    resp = requests.get(url, params=params, timeout=60)
    resp.raise_for_status()
    # Response has 2 header rows (site metadata, then column names) before data.
    df = pd.read_csv(io.StringIO(resp.text), skiprows=2)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    rename = {"temperature": "air_temperature"}
    df = df.rename(columns=rename)
    time_cols = [c for c in ("year", "month", "day", "hour", "minute") if c in df.columns]
    if time_cols:
        idx = pd.to_datetime(df[time_cols])
        df = df.drop(columns=time_cols).set_index(idx)
        df.index.name = "time"
    return df


def local_standard_utc_offset_hours(lat: float, lon: float) -> float:
    """STANDARD-time offset (no DST), per the brief's TIME CONVENTION rule.
    Evaluated in January so northern-hemisphere US zones are off DST."""
    from timezonefinder import TimezoneFinder
    from zoneinfo import ZoneInfo
    tf = TimezoneFinder()
    tzname = tf.timezone_at(lat=lat, lng=lon) or "Etc/UTC"
    jan1 = pd.Timestamp("2025-01-15 12:00", tz=ZoneInfo(tzname))
    return jan1.utcoffset().total_seconds() / 3600.0


def pull_track_b_clearsky_year(lat: float, lon: float, year: int) -> pd.DataFrame:
    """Ineichen clear-sky model, LOCAL STANDARD TIME (fixed offset, no DST
    shifts - matching the brief's TIME CONVENTION rule), hourly, matching
    the Track A schema so downstream code (S3) doesn't need to branch."""
    from pvlib.location import Location

    from zoneinfo import ZoneInfo
    offset_hr = int(round(local_standard_utc_offset_hours(lat, lon)))
    fixed_tz = ZoneInfo(f"Etc/GMT{-offset_hr:+d}")  # Etc/GMT sign is inverted from UTC offset
    loc = Location(lat, lon, tz=fixed_tz)

    n_hours = config.CALENDAR_HOURS.get(year, config.CALENDAR_HOURS_2026_YTD)
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


def fetch_grid_cell_year(grid_lat: float, grid_lon: float, year: int,
                          track_a_ok: bool, track_a_host: str) -> tuple[pd.DataFrame, str]:
    if track_a_ok:
        path_a = cache_path(grid_lat, grid_lon, year, "A")
        if os.path.exists(path_a):
            return pd.read_parquet(path_a), "A"
        try:
            df = pull_track_a_year(grid_lat, grid_lon, year, track_a_host)
            os.makedirs(os.path.dirname(path_a), exist_ok=True)
            df.to_parquet(path_a)
            return df, "A"
        except Exception as e:
            log.warning("Track A pull failed for (%s,%s,%d): %s - falling back to Track B",
                        grid_lat, grid_lon, year, e)

    path_b = cache_path(grid_lat, grid_lon, year, "B")
    if os.path.exists(path_b):
        return pd.read_parquet(path_b), "B_clearsky_stopgap"
    df = pull_track_b_clearsky_year(grid_lat, grid_lon, year)
    os.makedirs(os.path.dirname(path_b), exist_ok=True)
    df.to_parquet(path_b)
    return df, "B_clearsky_stopgap"


def run(sites: pd.DataFrame, years: list[int]) -> pd.DataFrame:
    sites = sites.copy()
    sites["grid_lat"], sites["grid_lon"] = zip(*sites.apply(
        lambda r: grid_cell(r["lat"], r["lon"]), axis=1))
    cells = sites[["grid_lat", "grid_lon"]].drop_duplicates()
    log.info("%d sites -> %d unique grid cells (%.0f%% dedup saving)",
              len(sites), len(cells), 100 * (1 - len(cells) / len(sites)))

    track_a_ok, track_a_host = probe_track_a_reachable()
    if not track_a_ok:
        log.warning("=" * 78)
        log.warning("TRACK A (NSRDB) UNREACHABLE FROM THIS SESSION. Falling back to "
                    "TRACK B (pvlib clear-sky, Ineichen) as an explicitly-flagged "
                    "stopgap so the rest of the pipeline can be built and tested. "
                    "PI/PRI computed this way is NOT decision-grade - it has no "
                    "weather-year signal. Re-run S2 once NSRDB access is restored.")
        log.warning("=" * 78)

    manifest = load_manifest()
    records = []
    n_cells = len(cells)
    for i, (_, cell) in enumerate(cells.iterrows()):
        for year in years:
            key = f"{cell['grid_lat']}_{cell['grid_lon']}_{year}"
            df, track = fetch_grid_cell_year(cell["grid_lat"], cell["grid_lon"], year,
                                              track_a_ok, track_a_host)
            manifest[key] = {"track": track, "rows": len(df), "ts": time.time()}
            records.append(dict(grid_lat=cell["grid_lat"], grid_lon=cell["grid_lon"],
                                 year=year, track=track, n_hours=len(df)))
        if (i + 1) % 20 == 0 or i == n_cells - 1:
            save_manifest(manifest)
            log.info("progress: %d/%d grid cells", i + 1, n_cells)

    save_manifest(manifest)
    return pd.DataFrame(records)


def main():
    sub = pd.read_parquet("data/subsample_sites.parquet")
    summary = run(sub, config.NSRDB_YEARS)
    summary.to_parquet("data/nsrdb_pull_summary.parquet", index=False)
    log.info("pull summary by track: %s", summary["track"].value_counts().to_dict())


if __name__ == "__main__":
    main()
