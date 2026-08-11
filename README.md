# Solar Underperformance Analysis (PI / PRI / Degradation / Faults)

Implements `BUILD_BRIEF` (PI/PRI methodology v1.2 + Fault Estimation Tracker
D-Band Method) against the FY19-FY26 production panel. Track A only:
NSRDB PSM3 + pvlib, no clear-sky fallback.

## Input data (not checked into git)

Raw inputs are large (production_long.csv is ~28MB, the workbook ~7MB) and
are supplied per-run rather than committed. Place them at:

```
data/raw/production_long.csv
data/raw/site_master.csv
data/raw/Solar_Production_and_Asset_Data_FY19_FY26.xlsx
data/raw/solar_assets_data.csv
```

All four are present as of the current run. `solar_assets_data.csv` (7,773
generator rows, 7,102 plants, 296 with >1 generator) feeds S4a's
time-varying DC capacity for phased builds.

## Run order

```
python3 s0_load.py       # CSVs -> parquet, COD construction, null/zero integrity
python3 s1_gates.py       # data quality funnel (reproduces Section 4 exactly)
```

See `data/funnel.csv` for the validated funnel output and `config.py` for
every constant/threshold used by the pipeline (nothing is inlined).

## Status

See the latest run report / conversation notes for current build status.
This is a large multi-stage build (NSRDB pull, hourly pvlib simulation,
D-Band fault classifier, hazard/frailty model, self-contained explorer) -
being built and validated incrementally per the brief's own recommended
build order (100-site stratified subsample first, full 6,204-site scale-up
as a tracked follow-up).
