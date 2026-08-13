#!/bin/bash
# Self-healing wrapper around s2_nsrdb.py. Keeps re-launching the pull
# until every cell-year is cached, sleeping and retrying automatically
# when the daily 10,000-request cap is hit (s2_nsrdb.py exits 3 on 3
# consecutive 429s) or on an unexpected crash. Safe to re-run: already
# cached cell-years are always skipped, so restarting never re-downloads
# or duplicates work.
set -u
cd /home/user/CarlosPVSolarTest

SITES_CSV="/tmp/claude-0/-home-user-CarlosPVSolarTest/bfcbec3c-e250-5567-a215-4c0a62049c22/scratchpad/expansion_sites_rest_of_fleet_v2.csv"
LOG="logs/s2_pull_rest_of_fleet.log"
SUPERVISOR_LOG="logs/s2_supervisor.log"
RATE_LIMIT_RETRY_SECONDS=900    # 15 min - cheap to re-probe (3 wasted requests if still capped)
CRASH_RETRY_SECONDS=300         # 5 min backoff on an unexpected (non-rate-limit) exit

slog() { echo "$(date -u +%Y-%m-%dT%H:%M:%S)Z SUPERVISOR $1" | tee -a "$SUPERVISOR_LOG"; }

slog "starting supervised NSRDB pull loop"
while true; do
  python3 s2_nsrdb.py --sites-csv "$SITES_CSV" --years 2019-2025 --cache-dir nsrdb_cache \
    --email carlos.martinez.dk@gmail.com >> "$LOG" 2>&1
  code=$?

  if [ "$code" -eq 3 ]; then
    slog "daily rate cap hit (exit 3) - sleeping ${RATE_LIMIT_RETRY_SECONDS}s before retrying"
    sleep "$RATE_LIMIT_RETRY_SECONDS"
    continue
  fi

  if [ "$code" -ne 0 ]; then
    slog "unexpected exit code $code - sleeping ${CRASH_RETRY_SECONDS}s before retrying"
    sleep "$CRASH_RETRY_SECONDS"
    continue
  fi

  # Clean exit (code 0): check whether the run's own summary line reported
  # zero failures. If it did, and nothing remains to pull, we're done.
  last_summary=$(grep "^.*S2 complete:" "$LOG" | tail -1)
  slog "clean run finished: $last_summary"
  failed_n=$(echo "$last_summary" | grep -oP '\d+(?= failed)')
  if [ "${failed_n:-1}" = "0" ]; then
    slog "0 failures on this pass - verifying nothing remains uncached"
    remaining=$(python3 - "$SITES_CSV" <<'PYEOF'
import csv, os, sys
sites_csv = sys.argv[1]
GRID_DEG = 0.04
def grid_cell(lat, lon):
    return (round(lat / GRID_DEG) * GRID_DEG, round(lon / GRID_DEG) * GRID_DEG)
cells = set()
with open(sites_csv) as f:
    for row in csv.DictReader(f):
        cells.add(grid_cell(float(row["lat"]), float(row["lon"])))
years = range(2019, 2026)
missing = 0
for lat, lon in cells:
    for year in years:
        path = f"nsrdb_cache/grid_lat={lat}/grid_lon={lon}/year={year}/weather_A.parquet"
        if not os.path.exists(path):
            missing += 1
print(missing)
PYEOF
)
    slog "cell-years still missing: $remaining"
    if [ "$remaining" = "0" ]; then
      slog "ALL CELL-YEARS CACHED - pull complete, stopping supervisor loop"
      break
    fi
  fi
  slog "more work remains - relaunching immediately"
  sleep 5
done
slog "supervisor loop exited"
