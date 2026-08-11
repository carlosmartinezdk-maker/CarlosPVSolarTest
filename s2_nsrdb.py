#!/usr/bin/env python3
"""Standalone NSRDB (PSM v4 GOES Aggregated) irradiance pull from developer.nlr.gov.

NO DEPENDENCY ON THE REST OF THIS REPO. This file is meant to be copied to
any machine with plain internet access -- Carlos's laptop, a VM, a cron job
-- and run there. It has no import of config.py or anything else in this
repository on purpose: the agent sandbox that develops the rest of the
pipeline may not have egress to developer.nlr.gov, and this script must not
require it to.

Usage:
    python s2_nsrdb.py preflight
        One cheap request against a known cell. Exits 0 on success, non-zero
        otherwise, and NAMES the failure class (proxy denial / DNS failure /
        auth failure / rate limit) rather than just failing.

    python s2_nsrdb.py pull --sites site_master.csv --cache-dir nsrdb_cache \\
        --email you@example.com [--dry-run] [--years 2019-2025]
        Dedupes sites onto the 4 km grid, then pulls one CSV per
        (grid cell, year), caching to parquet. Resumable: rerun after any
        interruption and it picks up where it left off.

Reads the API key from NLR_API_KEY (falling back to NREL_API_KEY). Never
hardcode it, never log it, never let it appear in a cache filename, the
manifest, or any error message.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, asdict
from pathlib import Path

BASE_URL = "https://developer.nlr.gov"
ENDPOINT = "/api/nsrdb/v2/solar/nsrdb-GOES-aggregated-v4-0-0-download.csv"
DATASET_VERSION = "GOES-aggregated-v4.0.0"

ATTRIBUTES = "ghi,dni,dhi,air_temperature,wind_speed,surface_albedo"
INTERVAL = 60
UTC = False  # API default is True -- wrong for this pipeline, must be explicit
LEAP_DAY = True  # API default is False -- would silently drop Feb 29

YEARS_AVAILABLE = range(1998, 2026)  # 1998-2025 inclusive, NLR has no 2026 yet
GRID_RESOLUTION_KM = 4.0
KM_PER_DEG_LAT = 111.0

RATE_LIMIT_MIN_INTERVAL_S = 1.0  # 1 request/second, CSV endpoint
DAILY_REQUEST_CAP = 10_000

# A cell known to have NSRDB coverage, used only for the preflight probe.
# (Golden, CO -- NLR's own home turf. Any onshore CONUS point would do.)
PREFLIGHT_LAT = 39.74
PREFLIGHT_LON = -105.17
PREFLIGHT_YEAR = 2023


def api_key() -> str:
    key = os.environ.get("NLR_API_KEY") or os.environ.get("NREL_API_KEY")
    if not key:
        print(
            "ERROR: no API key found. Set NLR_API_KEY (or NREL_API_KEY) in "
            "the environment before running this script. Do not pass it as "
            "a CLI argument.",
            file=sys.stderr,
        )
        sys.exit(2)
    return key


def snap_to_grid(lat: float, lon: float) -> tuple[float, float]:
    """Snap a (lat, lon) onto the ~4 km NSRDB grid.

    Longitude step is derived from the SNAPPED latitude band, not the raw
    input latitude -- two points a few meters apart can otherwise land on
    opposite sides of a latitude bin boundary, get slightly different
    lon_step values, and dedupe into different grid cells despite being
    well within one real 4 km cell.
    """
    lat_step = GRID_RESOLUTION_KM / KM_PER_DEG_LAT
    grid_lat = round(lat / lat_step) * lat_step
    lon_step = GRID_RESOLUTION_KM / (KM_PER_DEG_LAT * max(math.cos(math.radians(grid_lat)), 0.01))
    grid_lon = round(lon / lon_step) * lon_step
    return round(grid_lat, 6), round(grid_lon, 6)


def parse_years(spec: str) -> list[int]:
    """'2019-2025' or '2019,2020,2023' -> sorted list of ints, clamped to availability."""
    years: set[int] = set()
    for part in spec.split(","):
        part = part.strip()
        if "-" in part:
            lo, hi = part.split("-")
            years.update(range(int(lo), int(hi) + 1))
        elif part:
            years.add(int(part))
    unavailable = sorted(y for y in years if y not in YEARS_AVAILABLE)
    if unavailable:
        print(
            f"ERROR: years {unavailable} are outside NLR's published range "
            f"(1998-2025). 2026 is not available -- see brief Section 0.7.",
            file=sys.stderr,
        )
        sys.exit(2)
    return sorted(years)


def read_grid_cells(sites_path: Path) -> list[tuple[float, float]]:
    """Read a sites CSV (needs lat/lon or latitude/longitude columns) and
    dedupe onto the 4 km grid."""
    cells: set[tuple[float, float]] = set()
    with sites_path.open(newline="") as f:
        reader = csv.DictReader(f)
        fields = {name.lower(): name for name in (reader.fieldnames or [])}
        lat_col = fields.get("lat") or fields.get("latitude")
        lon_col = fields.get("lon") or fields.get("longitude")
        if not lat_col or not lon_col:
            print(
                f"ERROR: {sites_path} has no recognizable lat/lon columns "
                f"(looked for lat/latitude and lon/longitude, found "
                f"{reader.fieldnames}).",
                file=sys.stderr,
            )
            sys.exit(2)
        for row in reader:
            try:
                lat = float(row[lat_col])
                lon = float(row[lon_col])
            except (TypeError, ValueError):
                continue
            cells.add(snap_to_grid(lat, lon))
    return sorted(cells)


@dataclass
class FetchResult:
    outcome: str  # "success" | "proxy_denial" | "dns_failure" | "auth_failure" | "rate_limited" | "other_error"
    http_status: int | None
    detail: str


def classify_error(exc: Exception) -> FetchResult:
    """Turn a request failure into an actionable classification -- this is
    what makes the preflight check useful instead of just "it failed"."""
    if isinstance(exc, urllib.error.HTTPError):
        body = ""
        try:
            body = exc.read(2048).decode("utf-8", errors="replace")
        except Exception:
            pass
        deny_reason = exc.headers.get("x-deny-reason") if exc.headers else None
        if exc.code == 403 and (deny_reason == "host_not_allowed" or not body.strip().startswith("{")):
            return FetchResult(
                "proxy_denial", exc.code,
                "403 with no JSON body / host_not_allowed header -- this is "
                "an egress proxy policy denial, not an NLR auth failure. "
                "The request never reached developer.nlr.gov. Allowlist the "
                "host or run this script on a machine with plain internet "
                "access.",
            )
        if exc.code in (401, 403):
            return FetchResult(
                "auth_failure", exc.code,
                f"NLR rejected the API key (HTTP {exc.code}). Body: {body[:500]}",
            )
        if exc.code == 429:
            return FetchResult("rate_limited", exc.code, "NLR rate limit hit (429).")
        if exc.code == 410:
            return FetchResult(
                "other_error", exc.code,
                "410 Gone -- this means the URL is wrong (e.g. pointing at "
                "the retired developer.nrel.gov path), a bug in this "
                "script, not a transient failure. Do not retry blindly.",
            )
        return FetchResult("other_error", exc.code, f"HTTP {exc.code}: {body[:500]}")
    if isinstance(exc, urllib.error.URLError):
        reason = str(exc.reason)
        if "getaddrinfo" in reason or "Name or service not known" in reason or "nodename nor servname" in reason:
            return FetchResult(
                "dns_failure", None,
                f"DNS resolution failed for {BASE_URL} ({reason}). If this "
                f"machine has normal internet access, the domain itself may "
                f"be wrong -- double check it is developer.nlr.gov, not the "
                f"retired developer.nrel.gov.",
            )
        if "tunnel connection failed" in reason.lower() and "403" in reason:
            return FetchResult(
                "proxy_denial", 403,
                "CONNECT tunnel rejected with 403 before any TLS handshake "
                "to developer.nlr.gov -- this is a local/organizational "
                "egress proxy policy denial, not an NLR auth failure. The "
                "request never left this machine's network sandbox. "
                "Allowlist the host or run this script somewhere with "
                "plain internet access.",
            )
        return FetchResult("other_error", None, f"Connection error: {reason}")
    return FetchResult("other_error", None, f"Unexpected error: {exc!r}")


def build_url(lat: float, lon: float, year: int, email: str) -> str:
    params = {
        "api_key": api_key(),
        "wkt": f"POINT({lon} {lat})",  # longitude first
        "names": str(year),
        "interval": str(INTERVAL),
        "attributes": ATTRIBUTES,
        "utc": "false" if not UTC else "true",
        "leap_day": "true" if LEAP_DAY else "false",
        "email": email,
    }
    return f"{BASE_URL}{ENDPOINT}?{urllib.parse.urlencode(params)}"


def fetch_csv(lat: float, lon: float, year: int, email: str, timeout: float = 60.0) -> tuple[FetchResult, bytes | None]:
    url = build_url(lat, lon, year, email)
    req = urllib.request.Request(url, headers={"User-Agent": "s2_nsrdb.py/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return FetchResult("success", resp.status, "ok"), body
    except Exception as exc:  # noqa: BLE001 -- classify everything, this is a leaf script
        return classify_error(exc), None


def cmd_preflight(_: argparse.Namespace) -> int:
    print(f"Preflight: probing {BASE_URL}{ENDPOINT} for a known-good cell...")
    email = os.environ.get("NLR_CONTACT_EMAIL", "preflight@example.invalid")
    result, _ = fetch_csv(PREFLIGHT_LAT, PREFLIGHT_LON, PREFLIGHT_YEAR, email, timeout=15.0)
    print(f"Outcome: {result.outcome}")
    print(f"Detail:  {result.detail}")
    if result.outcome == "success":
        print("Preflight OK -- developer.nlr.gov is reachable and the key is valid.")
        return 0
    return 1


def cache_path(cache_dir: Path, grid_lat: float, grid_lon: float, year: int) -> Path:
    return (
        cache_dir
        / f"grid_lat={grid_lat}"
        / f"grid_lon={grid_lon}"
        / f"year={year}"
        / "data.csv"
    )


def load_manifest(cache_dir: Path) -> dict:
    manifest_path = cache_dir / "manifest.json"
    if manifest_path.exists():
        return json.loads(manifest_path.read_text())
    return {"dataset_version": DATASET_VERSION, "pulls": {}}


def save_manifest(cache_dir: Path, manifest: dict) -> None:
    manifest_path = cache_dir / "manifest.json"
    tmp = manifest_path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(manifest, indent=2, sort_keys=True))
    tmp.replace(manifest_path)


def cmd_pull(args: argparse.Namespace) -> int:
    sites_path = Path(args.sites)
    cache_dir = Path(args.cache_dir)
    years = parse_years(args.years)

    if not sites_path.exists():
        print(f"ERROR: sites file not found: {sites_path}", file=sys.stderr)
        return 2

    cells = read_grid_cells(sites_path)
    plan = [(lat, lon, year) for (lat, lon) in cells for year in years]
    print(f"{len(cells)} unique {GRID_RESOLUTION_KM:.0f} km grid cells x {len(years)} years = {len(plan)} cell-years.")

    cache_dir.mkdir(parents=True, exist_ok=True)
    manifest = load_manifest(cache_dir)

    remaining = [
        (lat, lon, year) for (lat, lon, year) in plan
        if not cache_path(cache_dir, lat, lon, year).exists()
    ]
    print(f"{len(plan) - len(remaining)} cell-years already cached, {len(remaining)} remaining.")

    if args.dry_run:
        for lat, lon, year in remaining:
            print(f"{lat},{lon},{year}")
        print(f"\n--dry-run: {len(remaining)} requests would be issued. Nothing fetched.")
        return 0

    if not remaining:
        print("Cache already complete for this plan.")
        return 0

    if not args.email:
        print("ERROR: --email is required by the NLR API (used for async delivery/contact).", file=sys.stderr)
        return 2

    day_count = 0
    day_start = time.monotonic()
    last_request_at = 0.0

    for i, (lat, lon, year) in enumerate(remaining, 1):
        if day_count >= DAILY_REQUEST_CAP:
            print(
                f"Daily cap of {DAILY_REQUEST_CAP} requests reached. Stop "
                f"here and resume tomorrow -- rerunning this command will "
                f"skip everything already cached."
            )
            return 0

        elapsed = time.monotonic() - last_request_at
        if elapsed < RATE_LIMIT_MIN_INTERVAL_S:
            time.sleep(RATE_LIMIT_MIN_INTERVAL_S - elapsed)

        result, body = fetch_csv(lat, lon, year, args.email)
        last_request_at = time.monotonic()
        day_count += 1

        if result.outcome != "success":
            print(f"[{i}/{len(remaining)}] {lat},{lon},{year} -> FAILED: {result.outcome}: {result.detail}", file=sys.stderr)
            if result.outcome in ("proxy_denial", "dns_failure", "auth_failure"):
                print("Stopping -- this failure class will not resolve by retrying.", file=sys.stderr)
                return 1
            if result.outcome == "rate_limited":
                print("Rate limited -- backing off 60s.", file=sys.stderr)
                time.sleep(60)
            continue

        dest = cache_path(cache_dir, lat, lon, year)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(body or b"")

        manifest["pulls"][f"{lat},{lon},{year}"] = {
            "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "utc": UTC,
            "leap_day": LEAP_DAY,
            "interval": INTERVAL,
            "attributes": ATTRIBUTES,
            "dataset_version": DATASET_VERSION,
        }
        if i % 50 == 0 or i == len(remaining):
            save_manifest(cache_dir, manifest)
            print(f"[{i}/{len(remaining)}] cached, {len(remaining) - i} left this run.")

    save_manifest(cache_dir, manifest)
    print("Pull complete for this invocation.")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    p_preflight = sub.add_parser("preflight", help="One cheap request to classify reachability/auth before a real pull.")
    p_preflight.set_defaults(func=cmd_preflight)

    p_pull = sub.add_parser("pull", help="Pull the full (grid cell, year) cache, resumable.")
    p_pull.add_argument("--sites", required=True, help="CSV with lat/lon (or latitude/longitude) columns, e.g. site_master.csv")
    p_pull.add_argument("--cache-dir", default="nsrdb_cache", help="Output cache directory (default: nsrdb_cache)")
    p_pull.add_argument("--years", default="2019-2025", help="Year range/list, default 2019-2025 (2026 is unavailable)")
    p_pull.add_argument("--email", default=os.environ.get("NLR_CONTACT_EMAIL", ""), help="Contact email, required by the API")
    p_pull.add_argument("--dry-run", action="store_true", help="Print the plan, fetch nothing")
    p_pull.set_defaults(func=cmd_pull)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
