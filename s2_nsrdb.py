#!/usr/bin/env python3
"""
S2 - Irradiance pull. STANDALONE BATCH JOB - NOT PART OF THE AGENT RUN.

Per the brief (Section 5 "Run the irradiance pull outside the agent"): this
script has NO import from the rest of this repo (no `import config`, no
reading data/*.parquet paths). It takes a list of (grid_lat, grid_lon, year)
cells and a cache directory, and does nothing else. Run it on a machine with
plain internet access - a laptop, a VM, a cron job - not inside an agent
sandbox. 33,586 cell-years at 1 req/sec with a 10,000/day cap is a four-day
job; no agent session should attempt that.

Every other stage in this repo (S3 onward) reads the resulting cache and
makes NO network calls. If a downstream stage raises a connection error,
that is a bug in that stage, not something to fix here.

USAGE
  # Preflight only - cheap, fails fast, classifies the failure precisely.
  python3 s2_nsrdb.py --preflight-only

  # Dry run - print the exact (cell, year) list without fetching anything.
  python3 s2_nsrdb.py --sites-csv sites.csv --dry-run

  # Real pull. sites.csv needs "lat,lon" columns (or pass --cells-csv with
  # grid_lat,grid_lon already deduplicated).
  python3 s2_nsrdb.py --sites-csv sites.csv --years 2019-2025 \
      --cache-dir nsrdb_cache

sites.csv / cells-csv are plain CSVs with no dependency on this repo's own
parquet schema, so this script can be copy-pasted anywhere on its own.

CACHE CONTRACT (the interface other stages rely on)
  <cache_dir>/grid_lat=<lat>/grid_lon=<lon>/year=<year>/weather_A.parquet
  <cache_dir>/manifest.json - one entry per (grid_lat, grid_lon, year) with
    track, rows, timestamp, and the exact request parameters used (utc,
    leap_day, interval, attributes) and the dataset version, per test 31.

API KEY: NLR_API_KEY env var, falling back to NREL_API_KEY. Never hardcoded,
never logged, never written into any cache filename or the manifest itself
(test 32).
"""
import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import requests

NSRDB_HOST = "developer.nlr.gov"
NSRDB_ENDPOINT_PATH = "/api/nsrdb/v2/solar/nsrdb-GOES-aggregated-v4-0-0-download.csv"
DATASET_VERSION = "GOES-aggregated-v4-0-0"
DEFAULT_YEARS = list(range(2019, 2026))  # 2019-2025; PSM v4 has no 2026 yet
DEFAULT_ATTRIBUTES = "ghi,dni,dhi,air_temperature,wind_speed,surface_albedo"
DEFAULT_INTERVAL = 60
GRID_DEG = 0.04  # ~4km
RATE_LIMIT_SECONDS = 1.0
MAX_REQUESTS_PER_DAY = 10_000

API_KEY_ENV_PRIMARY = "NLR_API_KEY"
API_KEY_ENV_FALLBACK = "NREL_API_KEY"


def log(msg: str) -> None:
    print(f"{datetime.now(timezone.utc).isoformat()} S2 {msg}", file=sys.stderr)


def get_api_key() -> str:
    return os.environ.get(API_KEY_ENV_PRIMARY) or os.environ.get(API_KEY_ENV_FALLBACK) or ""


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    return (round(lat / GRID_DEG) * GRID_DEG, round(lon / GRID_DEG) * GRID_DEG)


def cache_path(cache_dir: str, grid_lat: float, grid_lon: float, year: int) -> str:
    return os.path.join(cache_dir, f"grid_lat={grid_lat}", f"grid_lon={grid_lon}",
                        f"year={year}", "weather_A.parquet")


def manifest_path(cache_dir: str) -> str:
    return os.path.join(cache_dir, "manifest.json")


def load_manifest(cache_dir: str) -> dict:
    p = manifest_path(cache_dir)
    if os.path.exists(p):
        with open(p) as f:
            return json.load(f)
    return {}


def save_manifest(cache_dir: str, manifest: dict) -> None:
    os.makedirs(cache_dir, exist_ok=True)
    tmp = manifest_path(cache_dir) + ".tmp"
    with open(tmp, "w") as f:
        json.dump(manifest, f, indent=2)
    os.replace(tmp, manifest_path(cache_dir))


# --------------------------------------------------------------------------
# Preflight - classify a failure in seconds, never after hours of pulling.
# --------------------------------------------------------------------------

PREFLIGHT_SUCCESS = "success"
PREFLIGHT_PROXY_DENIAL = "proxy_denial"
PREFLIGHT_DNS_FAILURE = "dns_failure"
PREFLIGHT_AUTH_FAILURE = "auth_failure"
PREFLIGHT_RATE_LIMITED = "rate_limited"
PREFLIGHT_UNKNOWN = "unknown_error"


def redact_key(text: str, api_key: str) -> str:
    """requests/urllib3 exception messages and response bodies can embed the
    full request URL, including api_key=... in the query string. Every
    string that might reach a log line or an exception message MUST go
    through this first (test 32: no secrets in outputs, and outputs
    includes this process's own stdout/stderr)."""
    if not api_key:
        return text
    return text.replace(api_key, "***REDACTED***")


def preflight(host: str = NSRDB_HOST, email: str = "carlos.martinez.dk@gmail.com") -> tuple[str, str]:
    """One cheap request against a single known cell (Denver, a NLR-relevant
    point). Returns (classification, human-readable detail). Never loops or
    retries - a policy denial or a dead domain should fail fast, not burn
    minutes finding that out."""
    api_key = get_api_key()
    url = f"https://{host}{NSRDB_ENDPOINT_PATH}"
    params = {
        "api_key": api_key or "preflight-no-key",
        "wkt": "POINT(-104.99 39.74)",
        "names": "2023",
        "interval": "60",
        "attributes": "ghi",
        "utc": "false",
        "leap_day": "true",
        "email": email,
    }
    try:
        resp = requests.get(url, params=params, timeout=10)
    except requests.exceptions.ConnectionError as e:
        msg = redact_key(str(e), api_key)
        if "Tunnel connection failed: 403" in msg or "ProxyError" in msg:
            return PREFLIGHT_PROXY_DENIAL, (
                f"local egress proxy rejected the CONNECT tunnel to {host} - "
                f"host not on the sandbox allowlist. Add '{host}' to the "
                "environment's network egress allowlist (an environment "
                "setting, not a code fix). Detail: " + msg
            )
        if "Name or service not known" in msg or "nodename nor servname" in msg or "getaddrinfo" in msg:
            return PREFLIGHT_DNS_FAILURE, f"DNS lookup for {host} failed - domain does not resolve. {msg}"
        return PREFLIGHT_UNKNOWN, msg
    except requests.exceptions.RequestException as e:
        return PREFLIGHT_UNKNOWN, redact_key(str(e), api_key)

    if resp.status_code == 403 and "x-deny-reason" in resp.headers:
        return PREFLIGHT_PROXY_DENIAL, f"proxy denial header x-deny-reason={resp.headers['x-deny-reason']}"
    if resp.status_code == 429:
        return PREFLIGHT_RATE_LIMITED, "429 rate limited on the preflight request itself - back off and retry later"
    if resp.status_code in (401, 403):
        return PREFLIGHT_AUTH_FAILURE, (
            f"HTTP {resp.status_code} with a real TLS/HTTP response from {host} - bad or "
            f"missing API key, not a network block. Body: {redact_key(resp.text[:300], api_key)}"
        )
    if resp.status_code == 200:
        return PREFLIGHT_SUCCESS, "OK"
    return PREFLIGHT_UNKNOWN, f"HTTP {resp.status_code}: {redact_key(resp.text[:300], api_key)}"


# --------------------------------------------------------------------------
# Pull
# --------------------------------------------------------------------------

_last_request_ts = 0.0


def _rate_limit() -> None:
    global _last_request_ts
    wait = RATE_LIMIT_SECONDS - (time.monotonic() - _last_request_ts)
    if wait > 0:
        time.sleep(wait)
    _last_request_ts = time.monotonic()


def pull_cell_year(lat: float, lon: float, year: int, api_key: str, email: str) -> "pd.DataFrame":
    import pandas as pd
    _rate_limit()
    url = f"https://{NSRDB_HOST}{NSRDB_ENDPOINT_PATH}"
    params = {
        "api_key": api_key,
        "wkt": f"POINT({lon} {lat})",
        "names": str(year),
        "interval": str(DEFAULT_INTERVAL),
        "attributes": DEFAULT_ATTRIBUTES,
        "utc": "false",
        "leap_day": "true",
        "email": email,
        "full_name": "Carlos+Martinez",
        "affiliation": "SkySpecs",
        "reason": "PI_PRI_underperformance_analysis",
    }
    resp = requests.get(url, params=params, timeout=60)
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        raise requests.exceptions.HTTPError(redact_key(str(e), api_key), response=resp) from None
    df = pd.read_csv(io.StringIO(resp.text), skiprows=2)
    df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    df = df.rename(columns={"temperature": "air_temperature"})
    time_cols = [c for c in ("year", "month", "day", "hour", "minute") if c in df.columns]
    if time_cols:
        idx = pd.to_datetime(df[time_cols])
        df = df.drop(columns=time_cols).set_index(idx)
        df.index.name = "time"
    return df


def read_cells_from_sites_csv(path: str) -> list[tuple[float, float]]:
    cells = set()
    with open(path) as f:
        for row in csv.DictReader(f):
            lat, lon = float(row["lat"]), float(row["lon"])
            cells.add(grid_cell(lat, lon))
    return sorted(cells)


def read_cells_from_cells_csv(path: str) -> list[tuple[float, float]]:
    cells = []
    with open(path) as f:
        for row in csv.DictReader(f):
            cells.append((float(row["grid_lat"]), float(row["grid_lon"])))
    return cells


def run(cells: list[tuple[float, float]], years: list[int], cache_dir: str,
        dry_run: bool, email: str) -> None:
    total = len(cells) * len(years)
    log(f"{len(cells)} unique grid cells x {len(years)} years = {total} cell-years")

    if dry_run:
        for lat, lon in cells:
            for year in years:
                print(f"{lat},{lon},{year}")
        log(f"dry run: would fetch {total} cell-years, wrote the list to stdout")
        return

    api_key = get_api_key()
    if not api_key:
        log(f"ERROR: no API key in {API_KEY_ENV_PRIMARY} or {API_KEY_ENV_FALLBACK}")
        sys.exit(1)

    manifest = load_manifest(cache_dir)
    est_seconds = total * RATE_LIMIT_SECONDS
    log(f"estimated minimum wall time at {RATE_LIMIT_SECONDS}s/request: "
        f"{est_seconds/3600:.1f} hours ({total} requests, {MAX_REQUESTS_PER_DAY}/day cap "
        f"-> {total/MAX_REQUESTS_PER_DAY:.1f} days minimum if run continuously)")

    done, skipped, failed = 0, 0, 0
    for i, (lat, lon) in enumerate(cells):
        for year in years:
            key = f"{lat}_{lon}_{year}"
            path = cache_path(cache_dir, lat, lon, year)
            if os.path.exists(path):
                skipped += 1
                continue
            try:
                df = pull_cell_year(lat, lon, year, api_key, email)
                os.makedirs(os.path.dirname(path), exist_ok=True)
                df.to_parquet(path)
                manifest[key] = {
                    "grid_lat": lat, "grid_lon": lon, "year": year,
                    "rows": len(df), "pulled_at": datetime.now(timezone.utc).isoformat(),
                    "dataset_version": DATASET_VERSION,
                    "request_params": {"utc": False, "leap_day": True,
                                       "interval": DEFAULT_INTERVAL,
                                       "attributes": DEFAULT_ATTRIBUTES},
                }
                done += 1
            except Exception as e:
                log(f"FAILED {key}: {redact_key(str(e), api_key)}")
                failed += 1
        if (i + 1) % 20 == 0 or i == len(cells) - 1:
            save_manifest(cache_dir, manifest)
            log(f"progress: {i+1}/{len(cells)} cells | pulled {done} | cached {skipped} | failed {failed}")

    save_manifest(cache_dir, manifest)
    log(f"complete: {done} pulled, {skipped} already cached, {failed} failed, "
        f"{len(manifest)} total manifest entries")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--sites-csv", help="CSV with lat,lon columns")
    ap.add_argument("--cells-csv", help="CSV with grid_lat,grid_lon columns, already deduplicated")
    ap.add_argument("--years", default="2019-2025", help="e.g. 2019-2025 or 2019,2020,2023")
    ap.add_argument("--cache-dir", default="nsrdb_cache")
    ap.add_argument("--email", default="carlos.martinez.dk@gmail.com")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--preflight-only", action="store_true",
                     help="run only the preflight check and exit")
    args = ap.parse_args()

    if args.preflight_only:
        classification, detail = preflight(email=args.email)
        log(f"preflight: {classification} - {detail}")
        sys.exit(0 if classification == PREFLIGHT_SUCCESS else 1)

    if not args.dry_run:
        # Dry-run needs no connectivity at all - it's for planning/costing
        # the pull before network access is even sorted out. A real pull
        # gates on preflight so a dead host or bad key fails in seconds.
        classification, detail = preflight(email=args.email)
        log(f"preflight: {classification} - {detail}")
        if classification != PREFLIGHT_SUCCESS:
            log("ABORTING: preflight did not succeed. Fix the cause above before pulling. "
                "This is intentional - failing in seconds beats discovering a dead host or a "
                "bad key three hours into a multi-day pull.")
            sys.exit(1)

    if "-" in args.years:
        lo, hi = args.years.split("-")
        years = list(range(int(lo), int(hi) + 1))
    else:
        years = [int(y) for y in args.years.split(",")]

    if args.cells_csv:
        cells = read_cells_from_cells_csv(args.cells_csv)
    elif args.sites_csv:
        cells = read_cells_from_sites_csv(args.sites_csv)
    else:
        log("ERROR: pass --sites-csv or --cells-csv (or --preflight-only / --dry-run alone "
            "still needs one of these to know what to fetch)")
        sys.exit(1)

    run(cells, years, args.cache_dir, args.dry_run, args.email)


if __name__ == "__main__":
    main()
