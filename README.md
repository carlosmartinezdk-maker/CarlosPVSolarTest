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
data/raw/solar_assets_data.csv   # NOT YET PROVIDED, see Open Items
```

## Known gap: solar_assets_data.csv

The generator-grain asset file (required for Part 6 Step C1, time-varying DC
capacity on the 257 phased-build sites) was not included in the input set for
this run. `s0_load.py` emits an empty `generators.parquet` placeholder and
falls back to constant capacity (`site_master.mwdc`) fleet-wide. Sites with
`generators > 1` in site_master (294 pre-gate, tracked exactly at the
scoreable-funnel stage) are flagged `is_phased_build_unadjusted` and should
carry a downstream data-quality flag until the real file is supplied.

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
