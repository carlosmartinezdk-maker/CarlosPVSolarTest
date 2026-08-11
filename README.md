# Solar Underperformance Analysis (PI / PRI / Degradation / Faults)

Implements the PI/PRI methodology v1.2 + Fault Estimation Tracker D-Band
Method against the FY19-FY26 production panel. Track A only: NSRDB PSM v4
GOES Aggregated + pvlib, no silent clear-sky fallback.

## SECURITY: rotate the NLR API key

A key was pasted in plain text in chat on 11 August 2026. Per the brief's
own Section 11 item 3, **treat it as compromised** - it is not used
anywhere in this codebase. Reissue at `https://developer.nlr.gov/signup/`,
set the new one as the `NLR_API_KEY` environment variable (never as a
literal in code, a commit, or a chat message again), and `NREL_API_KEY`
is accepted as a compatibility fallback. `.gitignore` excludes `.env`.

## NSRDB access: S2 is now a standalone batch job, run OUTSIDE this repo's pipeline

`s2_nsrdb.py` has **no import from the rest of this repo**. It takes a CSV
of sites (or already-deduplicated grid cells) and a cache directory, and
does nothing else - copy it to any machine with plain internet access (a
laptop, a VM, a cron job) and run it there. The rest of the pipeline (S3
onward) only ever reads the resulting cache; nothing past S2 makes a
network call.

```
# Fails fast (~1s) and names the exact cause - proxy denial, DNS failure,
# or a real auth error - without needing a sites list.
python3 s2_nsrdb.py --preflight-only

# Print the exact (grid_lat, grid_lon, year) list a real pull would fetch,
# with no network access needed at all - useful for costing/handoff.
python3 s2_nsrdb.py --sites-csv data/subsample_sites_latlon.csv --dry-run

# The real pull (needs NLR_API_KEY set and developer.nlr.gov reachable):
python3 s2_nsrdb.py --sites-csv <lat,lon CSV> --years 2019-2025 \
    --cache-dir nsrdb_cache
```

**As of 11 August 2026, this environment CAN reach `developer.nlr.gov`** -
confirmed via `--preflight-only` (`success`), after network egress was
enabled for this session and the NLR API key was rotated (the key pasted
in chat earlier that day was treated as compromised and retired; the
replacement is set as `NLR_API_KEY`, never pasted in chat again). The
100-site validation subsample's real Track A pull (707 cell-years) has
been run from here - see `run_report.md` for the exact track mix each run
used. Note: NSRDB's `utc=false` response is local **standard** time with
no tz metadata; `s2_nsrdb.py` localizes it to the site's fixed
(non-DST) UTC offset via `timezonefinder`, matching the convention
`dev_clearsky_cache.py` already used for the stopgap.

The full-fleet pull (4,798 cells x 7 years = 33,586 cell-years) has
**not** been run - it's still a four-day job at the NLR rate limit
(1 req/sec, 10,000/day cap) that needs a fundamentally different execution
approach (background/routine-based with periodic check-ins across days,
not a single session) and requires explicit go-ahead before starting.

Prior to network access being enabled, this sandbox could not reach
`developer.nlr.gov` at all - `--preflight-only` classified it precisely as
a `proxy_denial` (the local egress proxy rejecting the CONNECT tunnel
before any TLS handshake). For development/testing without network access,
`dev_clearsky_cache.py` fills the same cache directory with a pvlib
clear-sky (Ineichen) stopgap instead (`weather_B.parquet`, never mistaken
for real data - `s3_model.py` always prefers `weather_A.parquet` where
both exist, and tags every row computed from the stopgap
`weather_track="B_clearsky_stopgap"`). **No PI/PRI/fault/dollar number
produced against Track B is decision-grade.** See `run_report.md` for
exactly which track each run used - `s11_explorer.py`'s
`meta.decision_grade` is computed from the actual
`data/nsrdb_pull_summary.parquet` track mix, not hardcoded.

## Input data (not checked into git)

Raw inputs are large and are supplied per-run rather than committed. Place
them at:

```
data/raw/production_long.csv
data/raw/site_master.csv
data/raw/Solar_Production_and_Asset_Data_FY19_FY26.xlsx
data/raw/solar_assets_data.csv
```

All four are present as of the current run. `solar_assets_data.csv` (7,773
generator rows, 7,102 plants, 296 with >1 generator) feeds S4a's
time-varying DC capacity for phased builds.

## 2026 handling (Section 0.7)

NSRDB PSM v4 covers 1998-2025 only - there is no 2026 irradiance. 2026
(Jan-May YTD) is still scored, but differently:
- PI and PR_T are always null for 2026 (never substituted with a clear-sky
  guess).
- SY and PRI are still computed (SY needs no irradiance).
- The peer health filter for 2026 screens on each peer's **2025 mean PI**,
  carried forward (`peer_health_carried_forward=True`), since there is no
  2026 PI to screen on.
- 2026 can never produce a qualified LEAD (the decision matrix needs both
  PI and PRI); it surfaces as `PRI_ONLY_UNCONFIRMED` instead.

## Run order

```
python3 s0_load.py        # CSVs -> parquet, COD construction, null/zero integrity
python3 s1_gates.py       # data quality funnel (reproduces Section 4 exactly)
python3 subsample.py      # stratified 100-site validation subsample
# S2 is standalone and out of band - see "NSRDB access" above. Either:
python3 s2_nsrdb.py --sites-csv <csv> --years 2019-2025          # real pull, needs egress + key
python3 dev_clearsky_cache.py --sites-csv <csv> --years 2019-2025  # dev-only stopgap, this sandbox
python3 s3_model.py       # hourly pvlib chain -> monthly expected generation (reads the cache only)
python3 s4_indices.py     # PI, PR_T, SY, peers, PRI
python3 s5_decision.py    # lead matrix
python3 s7_trajectory.py  # degradation slopes, envelope/gap, warranty clock
python3 s6_signatures.py  # D-Band fault classifier (runs after S7)
python3 s8_ledger.py      # event ledger, hazard bands, credibility
python3 s9_dollars.py     # target/gap/recoverable/value
python3 s10_report.py     # run_report.md + call list CSV
python3 s11_explorer.py   # builds explorer.html (self-contained, open by double-click)
```

See `data/funnel.csv` for the validated funnel output and `config.py` for
every constant/threshold used by the pipeline (nothing is inlined).

## Status

See `run_report.md` (generated by `s10_report.py`) for current build
status, test results, and caveats. The full S0-S11 pipeline (including
`explorer.html`) runs end-to-end on the 100-site validation subsample -
open `explorer.html` by double-click, no server needed. It's been checked
in a real headless browser (Playwright/Chromium): all three views render,
row click and j/k/Enter/Esc navigation work, filters and CSV export work,
triage state (call/dismiss/notes) persists across a reload via
localStorage, and deep links (`#site=...`) load directly into Site Detail.

The 100-site subsample now runs against real Track A NSRDB weather (see
"NSRDB access" above) - `run_report.md`'s TEST 11 (degradation sanity)
median beta_excess at 4+ years lands at essentially the -0.5%/yr target
against real weather, not just the clear-sky stopgap.

Full 6,204-site scale-up (real NSRDB pull, then re-running S3 onward) is a
tracked follow-up. Network access and raw input data are no longer the
blocker - it's purely the 4-day pull time at the NLR rate limit, deferred
pending explicit go-ahead and a background/routine-based execution
approach spanning multiple days.

## Known limitations this run

- 100-site subsample scale, not the full 6,204-site fleet - the single
  biggest caveat on every number now that Track A is in use (see "NSRDB
  access" above). `s11_explorer.py`'s Assumptions panel reports
  `decision_grade` computed from the real weather-track mix each run, not
  a hardcoded `false`.
- S8 (ledger/hazard/credibility) and S9 (dollars) are built and smoke-tested
  on the subsample but are not statistically meaningful at n~100 sites -
  the brief's own build order defers them to after full-scale NSRDB pull.
- Vintage-cohort stepwise degradation term (Section 7 identification fix)
  deferred to the full-scale run, where cohort bins have enough sites.
- Explorer's "map" is a plain lat/lon scatter (no basemap/state outlines,
  to stay dependency-free and self-contained) - labeled as approximate.
