# Solar Underperformance Analysis (PI / PRI / Degradation / Faults)

## Build Brief for Claude Code — v2, 2019–2026 Panel

| | |
|---|---|
| **Prepared** | 11 August 2026 (supersedes the v1 brief, FY22–FY26 panel) |
| **Owner** | Carlos, Finance & Revenue Operations, SkySpecs |
| **Methodology** | `PI_PRI_Methodology_v2.md` (v1.2, August 2026) |
| **Classifier** | Fault Estimation Tracker — D-Band Method (companion to Part 7) |
| **Data** | `Solar_Production_and_Asset_Data_FY19_FY26.xlsx`, `production_long.csv`, `site_master.csv`, `solar_assets_data.csv` |
| **Track** | **TRACK A** — NSRDB (PSM v4, GOES Aggregated) + pvlib. Do NOT fall back to Track B clear-sky without saying so in writing. |
| **Irradiance host** | **`developer.nlr.gov`** — NREL was renamed the National Laboratory of the Rockies; `nrel.gov` was retired 29 May 2026 and does not redirect. See Section 5. |
| **PPA** | **FIXED at 40 USD/MWh** (set by Carlos, August 2026) |

This brief is self-contained. Every equation, threshold and constant needed to execute is restated below. If you also have the methodology markdown, it is the authority wherever the two disagree.

### What changed since v1

- The panel went from 3 usable years to 8 (2019 to 2026 YTD).
- Every year is now EIA-923 at full precision. The 200-site, k-rounded production export is gone, and with it the quantisation-noise problem. **Delete any rescaling or noise-gating logic written against v1.**
- Scoreable sites: 1,138 → 6,204. Sites with 4+ years: 10 → 4,396.
- **Part 7** (event ledger and predictive fault risk) **is now buildable.** It was stubbed in v1 for lack of history. 3,682 scoreable sites have 5+ years.
- PPA is fixed at 40 USD/MWh. That blocker is closed.
- **New requirement:** an interactive explorer interface. See [Section 8](#section-8--the-explorer-interface).
- **The fault signature classifier has arrived.** The D-Band Method is specified in full at [S6](#s6--fault-signature--the-d-band-method). Nothing is blocked. Build the whole pipeline.
- **The irradiance source moved and changed version.** NREL is now the National Laboratory of the Rockies; `developer.nrel.gov` was retired on 29 May 2026 with no redirect, and PSM v3.2.2 is deprecated in favour of PSM v4 (GOES Aggregated). Any code or memory pointing at `developer.nrel.gov/api/nsrdb/v2/solar/psm3-2-2-download` is dead on both counts. Section 5 is rewritten.

---

## Section 0 — No blockers. Six interpretation calls, with defaults.

The classifier is specified (S6). Everything is buildable. Six points are under-determined where the D-Band tracker meets this dataset and the methodology. Each has a recommended default below — implement the default, make it a named config flag, and put the list in front of Carlos. **Do not stall on any of them.**

### 0.1 What "seasonally-calibrated PI" means under Track A

The tracker sets `score = PRI` where a valid peer group exists, else "seasonally-calibrated PI". Under Track A, PI is already absolute and needs no fleet calibration — that was a Track B repair. But a residual seasonal bias in the model (transposition, temperature, the static loss stack) is real.

> **Default:** `score_fallback = PI_adj = PI / median over the region of PI in that month` — the same quantity S7b already builds to strip the shared weather signal. It is seasonal, it is a calibration, and it reuses machinery you have. Tag those site-months `benchmark_mode = "physical"`, which Step 5 already downgrades one confidence level.

### 0.2 The two dollar formulas disagree — this one moves money

| Source | Formula | Benchmark |
|---|---|---|
| Methodology Part 8 | `T = median(SY_peer) x PRI_P75 x P_dc`; `G = max(T - E_act, 0)`; `$ = G x rho x PPA` | peer **P75** |
| Tracker quick estimate | `$ = D x SY_peer x DC x REC% x PPA` | peer **median** |

Part 8 is larger by the factor `PRI_P75`, about 5.6% on the reference fleet. The tracker labels its own version a "quick estimate".

> **Default:** Part 8 (P75) is the authoritative figure and the one that ranks the call list. Compute the tracker formula alongside it as `value_usd_quick`, show both in the explorer, and assert they stay within 15% of each other — a bigger divergence means a peer-set problem, not a rounding difference.

### 0.3 Where the fault threshold sits

Band 0.00–0.03 is NOISE. Band 0.03–0.08 is "watch, do not call".

> **Default:** `D < 0.03` → signature NONE. `0.03 <= D < 0.08` → signature recorded with `fault_flag = FALSE`: it appears in the explorer, but is excluded from episode counting, from exposure-weighted rates, and from every dollar figure. `D >= 0.08` → classified fault, `fault_flag = TRUE`.

This cut is not arbitrary: `D >= 0.08` is exactly `score < 0.92`, so the fault threshold and the lead threshold in S5 are the same line. That internal consistency is a good sign — preserve it.

### 0.4 Test scope — the discriminators are not all per-month

Step 4 mixes three scopes and the tracker does not say so:

| Scope | Tests |
|---|---|
| Month-level | OUTAGE (`D >= 0.70` in any single month) |
| Run-level | BLOCK (flat across >= 2 months, step onset); SOILING (monotonic rise over >= 3 months, then a drop) |
| Year-level | TRACKER (corr with daylight across the year); DEGRADATION (>= 8 months, CV < 0.35); BOS (CV >= 0.50 across the year, non-consecutive spikes) |

> **Default:** evaluate in that order. Assign OUTAGE months first, then test runs of consecutive deficit months for BLOCK and SOILING and claim the months they win, then apply the year-level winner to whatever deficit months remain unclaimed. Resolve any collision with the tracker's stated tie-break: `OUTAGE > BLOCK > SOILING > TRACKER > DEGRADATION > BOS`.

This lets one site carry spring soiling and an autumn block outage in the same year, which a single year-level label cannot express.

### 0.5 The block-fraction lookup is ambiguous at the +/-0.03 tolerance

The listed fractions are as little as 0.008 apart, so the tolerance windows overlap heavily. Measured across D = 0.04 to 0.75: **mean 1.65 candidate fractions, maximum 5, and 51% of the range matches more than one.** At D = 0.10 the candidates are 1/12, 1/10, 1/9 and 1/8.

> **Default:** take the NEAREST listed fraction, not the first within tolerance, and record `n_candidates` alongside it. Report the fraction as indicative sizing only, never as a count of failed inverters, and show `n_candidates` in the explorer so nobody quotes "1 of 10" to an owner when four readings fit equally well.

Honour the tracker's own guard: a fraction match is meaningless unless the run is ALSO flat (std of D < 0.05) and started with a step (D up >= 0.08 from the prior month).

### 0.6 G2 (SNOW) cannot be evaluated for 2026

The gate needs `mean(score)` over April–October of the same year. 2026 has January to May only, so the Nov–Mar winter months of 2026 have no summer baseline.

> **Default:** for 2026 winter months, evaluate G2 against the prior year's April–October mean and flag `benchmark_year_borrowed = TRUE`. Where the prior year is also missing, skip G2 and let the month fall through to Step 2, tagged `snow_gate_unevaluated`.

### 0.7 NSRDB has no 2026 data, so 2026 gets no PI

PSM v4 GOES Aggregated publishes years **1998 through 2025**. 2026 is not available, and the NSRDB announcements page confirms 2025 is the newest western-hemisphere release. The 2026 YTD tab covers January to May 2026, so **there is no measured irradiance to model it against.**

This is not fatal, because **PRI needs no irradiance at all** — it is a peer comparison, and the D-Band classifier already uses PRI as its primary score. So 2026 stays scoreable, but differently.

> **Default:**
> - Score 2019–2025 fully (PI, PR_T, PRI, everything).
> - For 2026: compute SY and PRI, set PI and PR_T to null, tag `no_irradiance_year = TRUE`.
> - **S5 cannot produce a LEAD for 2026** — the matrix requires both indices to flag. 2026 months can flag on PRI alone and should be surfaced as "PRI-only, unconfirmed", never as a qualified lead.
> - **The peer health filter breaks for 2026** (it screens peers on `PI >= 0.85`, and there is no 2026 PI). Fall back to screening peers on their own **2025 mean PI**, carried forward, and tag `peer_health_carried_forward = TRUE`. Do not silently skip the filter — an unscreened peer median is exactly the failure mode that produced a PRI of 2.23 in testing.
> - Re-run 2026 once NSRDB publishes it. Structure the cache and the pipeline so adding a year is a re-run, not a rewrite.

Practical effect: the NSRDB pull is 4,798 cells x **7** years, not 8 — **33,586 cell-years**.

---

## Section 1 — Objective

Three deliverables, in this order. Each depends on the one before it.

**Phase 1 — Compute the metrics.** For every scoreable site and every calendar month 2019-01 to 2026-05: expected generation (hourly physical model on measured weather, summed to month), PI, PR_T, specific yield, PRI, peer set and its confidence flags.

**Phase 2 — Determine faults and count them.** Classify each site-month into a signature, then per site and per year count duration (months affected) and incidence (distinct episodes), separate the fault ledger from the exposure ledger, fit trajectories, run the hazard and credibility layers, and convert the recoverable share into dollars at 40 USD/MWh.

**Phase 3 — An interface to navigate all of it.** A self-contained explorer that lets Carlos move from a fleet view, to a ranked triage list, to a single site's full history, and record a decision on each. Specified in Section 8. This is a first-class deliverable, not a reporting afterthought.

Keep the two commercial products separate throughout, because they sell differently and need different evidence:

| Product | Question | Layers | Status |
|---|---|---|---|
| **Detection** | What is broken now? | PI, PRI, signature | buildable |
| **Prevention** | What breaks next? | ledger, hazard, EAL | **now buildable** |

---

## Section 2 — Input files

**Prefer the CSVs for computation.** The workbook is the human-facing artifact and the authority on provenance; the CSVs carry identical data and load in a second instead of a minute.

### File 1: `production_long.csv` — 382,944 rows, the production fact table

| Column | Meaning |
|---|---|
| `site` | text, join key everywhere |
| `plant_id` | EIA plant id, float, null where unmatched |
| `year` | integer 2019–2026 |
| `period` | text label, `"2019"`..`"2025"`, `"2026 YTD"` |
| `month_num` | 1–12 |
| `month` | Jan..Dec |
| `month_start` | ISO date, first of the month |
| `mwh` | net generation, null when not reported |
| `reported` | boolean — **FALSE means not reported, NOT zero generation** |
| `is_partial_year` | TRUE only for the 2026 YTD rows |

360,519 of the 382,944 rows are reported. The rest are months a site did not report, which is not the same as a month it produced nothing.

### File 2: `site_master.csv` — 7,359 rows, the site dimension table

```
site, hybrid, plant_id, state, county, operator, utility, ba,
lat, lon, mwac, mwdc, dcac, summer_mw, winter_mw,
op_month, op_year, plant_age, latest_unit_year, generators,
tracking, single_axis, fixed_tilt, dual_axis, tilt, azimuth,
bifacial, module, match_method, years_present
```

### File 3: `solar_assets_data.csv` — 7,773 rows, GENERATOR grain

**Required, not optional.** `site_master` is the plant-level roll-up; you need the generator grain for one thing: Part 6 Step C1, time-varying DC capacity on phased builds. 257 scoreable sites have more than one generator.

Join on `plant_id`. Columns needed: `plant_id`, `generator_id`, `nameplate_capacity_mw`, `dc_net_capacity_mw`, `operating_year`, `operating_month`, `tilt_angle`, `azimuth_angle`, `tracking_type`, `crystalline_silicon`, `thin_film_cdte`, `latitude`, `longitude`.

### File 4: `Solar_Production_and_Asset_Data_FY19_FY26.xlsx`

11 tabs: Notes, 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 YTD, Site Master, Reconciliation. Schema in Section 3. Read the Notes tab once.

### File 5: Fault Estimation Tracker — D-Band Method

The classifier rules. Companion to methodology Part 7. Fully restated at S6 below, so the pipeline does not need the document open — but keep it in the repo as the authority.

### File 6 (external): NSRDB, PSM v4 GOES Aggregated

Pulled at runtime from `developer.nlr.gov`. Covers 1998–2025 only, so 2026 has no irradiance. See Sections 0.7 and 5.

### Still not provided

- **ISO curtailment feeds** (CAISO, ERCOT). Without them curtailed plants are mislabelled as faulty. The balancing authority code in `site_master` is the only proxy available; use BA-peer agreement to infer it.
- **Repair cost quotes.** The `rho_s` recovery fractions stay placeholders.
- **Contractual warranty terms.** Use the defaults in S7e, tagged as assumptions.

---

## Section 3 — Workbook schema (exact)

### The eight year tabs: 2019, 2020, 2021, 2022, 2023, 2024, 2025, 2026 YTD

Header row 1, data from row 2. Identical layout on all eight.

| Col | Field | Notes |
|---|---|---|
| A | Site | join key |
| B | Status | "OK" or "No data" |
| C | Mwac | AC nameplate, MW, from the asset register |
| D–O | Jan..Dec | monthly net generation, MWh, **full precision** |
| P | Total MWh | formula, `= SUM(D:O)` |
| Q | CF | formula, `= P / (C * hours in period)` |
| R | Hybrid | "Hybrid" or blank |
| S | Mwdc | DC capacity, MW |
| T | DC/AC | ratio |
| U | Tracking | Single-axis \| Fixed tilt \| Dual-axis \| Mixed \| Unknown |
| V | Tilt | degrees, blank for most trackers |
| W | Azimuth | degrees |
| X | Op. year | earliest generator COD year |
| Y | State | two-letter |
| Z | Total MWh (source) | annual total exactly as EIA reported it |

Row counts: 2019 = 3,301 · 2020 = 3,916 · 2021 = 4,497 · 2022 = 224 · 2023 = 5,629 · 2024 = 6,402 · 2025 = 6,694 · 2026 YTD = 1,249 · **total 31,912**

**Reading notes**

- An em-dash (U+2014) in a month cell means NOT REPORTED. A 0 means a real reported zero. Parse the em-dash to null, never to 0. **This is the single most damaging parsing mistake available here.**
- Columns P and Z should be equal on every row. Any row where they differ means a month failed to parse — assert it.
- CF uses exact calendar hours: 8,784 for the leap years 2020 and 2024, 8,760 otherwise, 3,624 for 2026 YTD (Jan–May).
- Columns S–Y are values, not formulas. At 31,912 rows, live INDEX/MATCH made the workbook unusable. `site_master.csv` is the single authority.
- 2026 YTD carries January to May only; June to December are all em-dashes.

### "Site Master" — 7,359 rows

| Col | Field | Col | Field |
|---|---|---|---|
| A | Site | Q | Op. year — COD year, earliest generator |
| B | Hybrid | R | Plant age (yrs) = 2026 − Op. year |
| C | EIA Plant Id | S | Latest unit year — differs from Q on phased builds |
| D | State | T | Generators — >1 means phased build, go to the asset CSV |
| E | County | U | Tracking type |
| F | Operator (EIA-923) | V | Single-axis (Yes/No) |
| G | Utility (asset data) | W | Fixed tilt (Yes/No) |
| H | Balancing Authority | X | Dual-axis (Yes/No) |
| I | Latitude | Y | Tilt angle — capacity-weighted, blank for most trackers |
| J | Longitude | Z | Azimuth angle — capacity-weighted |
| K | Mwac nameplate — `P_ac_i`, clipping ceiling | AA | Bifacial (Yes/No) |
| L | Mwdc — `P_dc_i`, normalisation denominator | AB | Module technology |
| M | DC/AC ratio | AC | Match method |
| N | Summer MW | AD–AK | 2019 … 2026 YTD, "Y" or blank |
| O | Winter MW | AL | Years present |
| P | Op. month — **use it, do not assume January** | | |

### "Notes" and "Reconciliation"

Provenance, conventions, the scoreable funnel and the tie-out. Every year ties to its source export with zero variance. Reproduce the funnel yourself in S1 and assert it matches.

---

## Section 4 — Data reality: what this panel supports

### Funnel

Reproduce this in S1; the Reconciliation tab carries the same numbers.

| Gate | Sites | Capacity |
|---|---|---|
| All unique sites | 7,359 | 152.3 GWac |
| drop hybrids | 7,204 | 144.2 GWac |
| require latitude and longitude | 6,974 | 144.2 GWac |
| require Mwdc present and > 0 | 6,419 | 117.7 GWac |
| require COD year | 6,419 | 117.7 GWac |
| require DC:AC within 1.05–1.65 | **6,204** | **113.8 GWac** |

= 6,204 scoreable sites, 29,040 site-years, 330,754 reported site-months.

### History depth — no longer the binding constraint

| Years present | Sites | Meaning |
|---|---|---|
| 1 | 126 | level only, no trajectory |
| 2 | 649 | catastrophic change only |
| 3 | 1,033 | |
| 4 | 714 | degradation separable — minimum for credible use |
| 5 | 760 | |
| 6 | 2,599 | vintage cohort effects estimable |
| 7 | 318 | |
| 8 | 5 | |

Cumulative: **2+ = 6,078 · 4+ = 4,396 · 5+ = 3,682 · 6+ = 2,922**

Consequences:

- **Part 6 trajectory:** fit wherever years >= 2, but only report a slope as decision-grade at 4+. Always emit beta with its standard error and t-statistic. At 2–3 years the median slope SE is around 3.79%/yr and most slopes will not clear |t| > 2; at 6 years they will.
- **Part 7 hazard model: BUILD IT.** 3,682 sites clear the 5-year bar and 2,922 clear 6. This is the layer that was impossible on the previous dataset.
- **Conviction tiers:** "Chronic" and "Event" are now genuinely separable for most of the fleet. Only 126 scoreable sites are stuck at "New".

### Where the panel is still weak — encode these, do not narrate them

**1. 2022 is a 224-site subset and is the one broken year in the panel.**

Its neighbours carry 4,497 sites (2021) and 5,629 (2023). Only 1,047 scoreable site-months survive from 2022, and its 13.0 TWh is roughly a tenth of what a complete 2022 should be, interpolating between 111.9 TWh in 2021 and 162.3 TWh in 2023.

*Proof it is partial, not real attrition:* 4,465 plants report in BOTH 2021 AND 2023, and only 158 of them appear in the 2022 file. **4,307 plants that were demonstrably operating and reporting on both sides of 2022 are simply absent from it.** Nothing physical explains that.

*Likely cause, for whoever re-pulls it:* the 2022 export has a different column layout from every other year — 71 columns carrying Grossgen and Gross Generation, against 97 columns carrying MMBtuPer_Unit, Tot_MMBtu and Elec_MMBtu in the 2019–2021 and 2023–2025 files. It came from a different EIA-923 page, schedule or vintage than the rest of the panel, and that alternate source covers far fewer plants. Re-pull 2022 from the SAME series as the other years and it should return roughly 5,000 plants.

Two further fingerprints confirm the set is skewed rather than representative: 102 of the 224 names contain "Hybrid" (46%, against about 4% fleet-wide), and their median COD is 2021 against 2017 for the 4,307 missing plants. It is weighted toward recent, storage-paired build.

> **Required until it is fixed:** treat 2022 absence as missing data, never as zero. Do not let a site's 2022 gap create a fault episode, break an episode run in two, or count against `exposure_months`. Flag any site whose 2022 is absent but whose 2021 and 2023 are present — that is a data gap, not an outage. Consider offering a "span 2022" option on trajectory fits that simply omits the year rather than treating it as a level shift.

**2. 2026 is five months and has no irradiance.** January to May only, so never compare a 2026 total to a full year without annualising, and never let a partial year feed an annual degradation slope as if complete. `exposure_months` for 2026 is at most 5. On top of that, NSRDB has not published 2026, so 2026 gets **PRI but no PI** — see Section 0.7 for the full handling, including the peer-health-filter fallback and the rule that 2026 cannot produce a qualified lead.

**3. Coverage expands over time.** 3,301 sites in 2019 against 6,694 in 2025. Most of that is genuine new build, but EIA reporting thresholds also change. A site missing from an early year was often operating and simply below the reporting cut. Missing is missing, never zero, never an outage.

**4. 155 hybrids are dropped.** Net generation on a storage-paired plant includes round-trip losses and reads as a permanent fault.

**5. 233 sites have no asset-register match**, so no capacity and no coordinates. They fail the gates. Filter `site_master.match_method` for "No match".

**6. Net generation is net of parasitic load** at every site. A small constant drag on PI, absorbed inside the 0.86 loss stack.

**7. EIA-923 runs 2–3 months behind.** Capital-allocation tool, not O&M alerting. Nothing in the interface should imply real-time.

**8. Tilt is blank for most single-axis sites** because trackers do not report it. Blank tilt is not flat-mounted. Branch on tracking type, never on tilt.

**9. Azimuth contains implausible values** including 0 (due north) and negatives. Sanity-check before it reaches the transposition model. For single-axis, azimuth is the tracker axis, typically 180.

**10. Tracking is Unknown on 34 scoreable sites and Mixed on 13.** Pick a documented default, flag them, and exclude them from headline fleet statements.

### Fleet composition (scoreable sites)

| Tracking | Count | | Module | Count |
|---|---|---|---|---|
| Fixed tilt | 3,242 | | Crystalline silicon | 5,549 |
| Single-axis | 2,858 | | Thin film CdTe | 538 |
| Dual-axis | 57 | | Thin film CIGS | 41 |
| Unknown | 34 | | Thin film other | 29 |
| Mixed | 13 | | Mixed | 17 |
| | | | Thin film a-Si | 9 |

Phased builds (more than one generator): 257. COD range: 2001 to 2025.

### Annual totals for reconciliation (MWh, increments already excluded)

| Year | MWh | Year | MWh |
|---|---|---|---|
| 2019 | 68,611,474 | 2023 | 162,330,524 |
| 2020 | 85,979,097 | 2024 | 215,425,229 |
| 2021 | 111,896,359 | 2025 | 290,808,705 |
| 2022 | 12,961,245 | 2026 YTD | 110,195,267 (Jan–May) |

---

## Section 5 — Environment and the NSRDB pull

**Dependencies:** python >= 3.11 · pvlib, pandas, numpy, scipy, statsmodels, requests, pyarrow, openpyxl. For Part 7: statsmodels for negative binomial GLM; lifelines or a hand-rolled Weibull fit for the hazard shapes.

### The host moved — read this before writing any request code

NREL was renamed the **National Laboratory of the Rockies (NLR)**. The transition is complete and irreversible:

| Date | Event |
|---|---|
| 1 Dec 2025 | DOE renames NREL to the National Laboratory of the Rockies |
| 2 Mar 2026 | `developer.nlr.gov` goes live; both domains work |
| 1–28 May 2026 | scheduled brownouts on `developer.nrel.gov`, returning `410 Gone` |
| **29 May 2026** | **`nrel.gov` and every subdomain stop resolving. No redirect.** |

- Base URL is now **`https://developer.nlr.gov`**. Anything pointing at `developer.nrel.gov` fails at DNS, not with a helpful error.
- **Existing API keys keep working** — only the domain changed. Carlos has issued a key; see the key handling note below.
- Support contact is now `nsrdb@nlr.gov`. Key signup is `https://developer.nlr.gov/signup/`.

### The dataset also changed version — PSM3 is deprecated

The v1 and early v2 briefs said "NSRDB PSM3". That is now doubly stale. On the NLR docs, **Physical Solar Model (PSM) v3.2.2 is listed under Deprecated**, replaced by GOES Aggregated v4.0.0.

**Use GOES Aggregated: PSM v4.**

```
GET|POST https://developer.nlr.gov/api/nsrdb/v2/solar/nsrdb-GOES-aggregated-v4-0-0-download.csv
```

- Coverage 1998 onwards, GOES east and west, **4 km spatial resolution**, 30-minute native.
- `interval` accepts 30 or 60. Use **60** — the model runs hourly and the extra resolution buys nothing here.
- Years available: **1998–2025. There is no 2026.** See Section 0.7.

### Request parameters — three defaults will silently corrupt the run

| Parameter | Required | Set it to | Why it matters |
|---|---|---|---|
| `api_key` | yes | from env | must be a query parameter even on POST |
| `wkt` | yes | `POINT(lon lat)` | note the order: **longitude first**. Nearest site to the point is used. |
| `names` | yes | the year, e.g. `2023` | one year per request for the CSV endpoint |
| `interval` | yes | `60` | |
| `attributes` | no | `ghi,dni,dhi,air_temperature,wind_speed,surface_albedo` | **defaults to returning ALL** — a much bigger payload |
| `utc` | no | **`false`** | **defaults to `true`.** We need local standard time (no DST) so month boundaries match EIA calendar months. Leaving the default shifts energy between months at every site. |
| `leap_day` | no | **`true`** | **defaults to `false`.** 2020 and 2024 are leap years; the default silently drops 29 February. |
| `email` | yes | a real address | used for async delivery and for contact |
| `full_name`, `affiliation`, `reason` | no | fill them in | courtesy, and it helps if you need support |

All six attributes the model needs are available under exactly these names: `ghi`, `dni`, `dhi`, `air_temperature`, `wind_speed`, `surface_albedo`. The response header rows carry SiteID, timezone, longitude, latitude and country — capture the timezone and coordinates into the cache metadata.

### Two response modes — pick the CSV one

- **`.json` (default)** is **asynchronous**: it returns an acknowledgement and emails a download link when the archive is built. Good for bulk polygons, useless for a resumable per-cell loop.
- **`.csv`** streams data directly in the response, but is **restricted to a single POINT and a single YEAR per request**.

Our cache key is exactly `(grid cell, year)`, so the `.csv` endpoint fits perfectly. Use it.

### Rate limits — these are the real constraint

| Limit | Value |
|---|---|
| `.csv` requests | **10,000 per day, no more than 1 per second** |
| all other formats | 2,000 per day, no more than 1 per 2 seconds |
| concurrent in-flight requests | **20** |
| queue fail-safe | service rejects requests when its queue is full; handle that error and back off |

These are deliberately lower than NLR's standard API rate limits because the data is expensive to generate.

**Do the arithmetic before you start.** 4,798 unique 4 km cells x 7 years (2019–2025) = **33,586 cell-years**. At 10,000 CSV requests per day that is a **minimum of four days** of pulling, and the 1-per-second ceiling means roughly 9.3 hours of wall-clock request time even if the daily cap were not binding. Plan for a multi-day, interruptible job.

### Consider the bulk S3 mirror instead

The complete NSRDB library is published for bulk access at `https://data.openei.org/s3_viewer?bucket=nrel-pds-nsrdb` (the bucket name still carries the old `nrel` prefix). For 33,586 cell-years this is very likely faster than the API and is not rate-limited. Evaluate it first; fall back to the API for stragglers. Note the bulk files are HDF5 on a different layout, so budget time for the reader.

### pvlib — verify, do not assume

`pvlib.iotools.get_psm3` and friends were written against `developer.nrel.gov`, and the published pvlib docs still show those URLs in their examples and defaults. The pvlib issue tracking this (#2701) is closed by PR #2705, so a fixed release likely exists — but **check the installed version at runtime rather than trusting either the docs or this brief**:

- inspect the function's default `url` and override it explicitly with the `url=` parameter pointing at the v4 GOES Aggregated endpoint
- if the installed pvlib has no working v4 helper, hand-roll the request with `requests` — it is a single GET with query parameters, and the CSV parse is trivial
- do NOT let a stale pvlib default silently send traffic to a dead domain; a DNS failure at hour three of a four-day pull is an expensive way to find out

### Network egress — the agent sandbox blocks this host by default

**Symptom.** A request to `developer.nlr.gov` fails before it leaves the machine. The local egress proxy rejects the `CONNECT` tunnel with `403 Forbidden`, so there is no TLS handshake and no HTTP request. Proxy diagnostics show `"kind": "connect_rejected"` and a detail like `gateway answered 403 to CONNECT (policy denial or upstream failure)`, or a response header `x-deny-reason: host_not_allowed`.

**This is not an authentication failure.** The API key is never transmitted — the connection dies at the proxy. Do not debug the key, do not regenerate it, do not re-check the environment variable. Encode the distinction so nobody loses an hour to it again:

| Where the 403 comes from | Signature | Meaning |
|---|---|---|
| Local egress proxy | `connect_rejected`, `x-deny-reason: host_not_allowed`, no TLS handshake, proxy address is loopback | host not on the sandbox allowlist |
| NLR | valid TLS, JSON body with an `errors` array | bad or missing API key, or a malformed request |

**Hosts to allowlist:**

| Host | Needed for |
|---|---|
| `developer.nlr.gov` | the NSRDB API itself — required |
| `mapfiles.nlr.gov` | async `.json` archive downloads, if the two-step workflow is used |
| `data.openei.org` | the bulk S3 mirror index — optional |
| `nrel-pds-nsrdb.s3.amazonaws.com` | bulk NSRDB objects — optional, only if the mirror route is taken |
| `nsrdb.nlr.gov` | announcements page, to check when 2026 lands — optional |

**Where to set it.** No domains are pre-allowed by default; the sandbox proxy enforces an allowlist.

- *Claude Code CLI:* add the hosts to `sandbox.network.allowedDomains` in `~/.claude/settings.json` (or the project's `.claude/settings.json`). A `WebFetch(domain:...)` allow rule also pre-allows a host.

  ```json
  {
    "sandbox": {
      "enabled": true,
      "network": {
        "allowedDomains": ["developer.nlr.gov", "mapfiles.nlr.gov"]
      }
    }
  }
  ```

- *Managed / hosted sessions:* an administrator sets this under Organization Settings → Capabilities → Code execution → Allow network egress. Note `allowManagedDomainsOnly` and `strictAllowlist`, if set, mean only managed entries are honoured and a local settings file will not help.
- *Known issue:* there are open reports that the "Additional allowed domains" list is ignored when the top-level mode is "Package managers only". If adding `developer.nlr.gov` alone has no effect, that is likely what is happening — escalate to whoever administers the org rather than assuming a typo.

**Do not work around it by disabling the sandbox.** The right answer is the next section.

### Run the irradiance pull outside the agent — it is a batch job, not an agent task

Even with the allowlist fixed, S2 does not belong inside an interactive agent session. It is **33,586 requests, rate-limited to 1 per second with a 10,000/day cap — a four-day job minimum.** No agent session survives that, and none should try.

**Decouple S2 completely.** Treat the irradiance cache as an input to the pipeline rather than a stage of it:

- `s2_nsrdb.py` is a **standalone script with no dependency on the rest of the repo**. It takes a list of `(grid_lat, grid_lon, year)` triples and a cache directory, and it does nothing else. It runs on Carlos's laptop, a VM, a cron job, or anywhere with plain internet access.
- Every other stage reads the cache directory and **never makes a network call**. S3 fails loudly with a clear message naming the missing partitions if the cache is incomplete, rather than silently modelling a partial fleet.
- The cache contract is the interface: parquet partitioned `grid_lat=/grid_lon=/year=`, with a `manifest.json` recording each pull's timestamp, the request parameters used (`utc`, `leap_day`, `interval`, `attributes`), and the API dataset version. Test 28 asserts the manifest is complete before S3 runs.
- Ship a `--dry-run` mode that emits the exact list of cell-years it would fetch, so the pull can be handed to someone else, split across machines, or costed before it starts.

This is better engineering regardless of the proxy. The four-day pull becomes a one-time asset that survives every subsequent re-run of the analysis, and the agent works against local parquet at full speed.

**Preflight, always.** Before the first request, S2 issues one cheap request against a single known cell and classifies the outcome: success, proxy denial, DNS failure, auth failure, or rate limit. It prints which one and exits non-zero on anything but success. Failing in five seconds with "host not on the sandbox allowlist — add `developer.nlr.gov`" is worth a great deal more than discovering it at hour three.

### API key handling

Read the key from the **`NLR_API_KEY`** environment variable, falling back to `NREL_API_KEY` for compatibility with older shells. **Never hardcode it. Never commit it. Never write it into the run report, the explorer, or any cached filename.** Add `.env` to `.gitignore` before the first commit.

### Pull design

- cache every response to parquet, partitioned by `grid_lat` / `grid_lon` / `year`
- dedupe sites onto the 4 km grid first: 6,204 sites collapse to 4,798 cells, a 23% saving
- make the loop fully resumable and idempotent; assume it gets interrupted, because over four days it will be
- checkpoint to a manifest so a restart is instant and never re-pulls a cell-year already on disk
- respect 1 request/second and cap in-flight at 20; treat `410 Gone` as a dead-domain bug in your own code, not a transient error
- build and test the whole pipeline on a stratified 100-site subsample first, and only then start the full pull

The P50/P90 layer (methodology Part 3, Step A6) needs 20+ years per site — roughly 96,000 additional cell-years, or ten days of API time. Make it a separate opt-in stage behind its own flag, and use the S3 mirror if it is ever switched on. It is not part of the default run.

## Section 6 — Constants

Put every one of these in a single config module. None inline in the maths.

### Physical and index constants

| Symbol | Meaning | Value |
|---|---|---|
| `gamma` | temperature coefficient | −0.0037 /degC c-Si; −0.0028 /degC CdTe (use c-Si for other thin film and Mixed; tag those sites) |
| `d` | annual degradation rate | 0.005 /yr c-Si; 0.004 /yr CdTe |
| `L` | static loss stack | 0.86 (soiling, mismatch, wiring, IAM, availability) |
| `eta_inv` | inverter efficiency | 0.985 |
| `PPA` | | **40.0 USD/MWh, fixed** |
| | PI / PRI decision threshold | 0.92 |
| | Peer health floor | PI >= 0.85 |
| | Peer set target | 15 |
| | Peer minimum | 4 (below this: no PRI, PI alone) |
| | Adaptive radius ladder | 150 → 250 → 400 → 600 km |
| | Peer age window | \|a_j − a_i\| <= 4 years |
| | Peer DC:AC window | \|rho_j − rho_i\| <= 0.20 |
| | Commissioning ramp exclusion | tau < 0.5 years |
| | Minimum scoreable months / site-yr | 6 |
| | Episode gap tolerance | 1 month |
| | `PRI_P75` benchmark | 0.75 quantile of fleet PRI — **compute it from this data.** The methodology observed 1.056 on a different fleet. Do not hardcode. |
| | Warranty defaults (assumed) | 2y EPC, 5–10y inverter, 10–12y module product, 25y module performance |

### NSRDB request constants

| Constant | Value |
|---|---|
| base URL | `https://developer.nlr.gov` |
| endpoint | `/api/nsrdb/v2/solar/nsrdb-GOES-aggregated-v4-0-0-download.csv` |
| API key env var | `NLR_API_KEY` (fallback `NREL_API_KEY`) |
| attributes | `ghi,dni,dhi,air_temperature,wind_speed,surface_albedo` |
| interval | 60 |
| utc | **false** (API default is true) |
| leap_day | **true** (API default is false) |
| years available | 1998–2025 — **no 2026** |
| scored years with irradiance | 2019–2025 |
| grid resolution | 4 km |
| unique cells to pull | 4,798 |
| cell-years to pull | 33,586 |
| rate limit, csv | 10,000/day, 1/second |
| max in-flight | 20 |

### D-Band classifier constants

All from the Fault Estimation Tracker.

| Constant | Value |
|---|---|
| noise ceiling | `D < 0.03` → NONE |
| watch band | `0.03 <= D < 0.08` → not a fault |
| fault floor | `D >= 0.08` → classify |
| outage floor | `D >= 0.70` |
| G1 curtailment: BA median score | < 0.92 |
| G1 site-to-BA tolerance | \|site − BA median\| <= 0.10 |
| G1 minimum plants in BA-month | 3 |
| G2 snow latitude floor | 37.0 degrees |
| G2 snow months | Nov, Dec, Jan, Feb, Mar |
| G2 summer health floor | mean(score, Apr–Oct) >= 0.95 |
| G3 clipping DC:AC floor | 1.35 |
| G3 clipping months | Apr, May, Jun, Jul, Aug |
| G3 clipping PRI floor | 0.95 |
| block flat tolerance | std(D across run) < 0.05 |
| block step onset | D rises >= 0.08 from the prior month |
| block fraction tolerance | +/- 0.03 (nearest match — see 0.5) |
| soiling rise | >= 3 months monotonic, total rise >= 0.06 |
| soiling reset drop | >= 0.05 the month after the rise |
| tracker daylight correlation | >= 0.50 |
| degradation persistence | D >= 0.05 in >= 8 months, CV(D) < 0.35 |
| degradation trajectory | year-on-year PI decline > 1.5%/yr |
| BOS dispersion | CV(monthly D) >= 0.50 |
| BOS spikes | >= 2 NON-consecutive months, D >= 0.15 |
| minimum winning score | 3 (below this → UNATTRIBUTED) |
| confidence HIGH | score >= 5, >= 8 healthy peers, >= 2 yrs |
| confidence MEDIUM | score 3–4, >= 4 healthy peers |

---

## Section 7 — Pipeline

### S0 — Load and normalise

Read `production_long.csv` and `site_master.csv`. Read `solar_assets_data.csv` for generator grain.

Keep null distinct from 0 everywhere downstream. Assert the null count matches the `reported == False` count exactly.

`COD = date(op_year, op_month, 1)`. Use the month; do not assume January.

Emit `production.parquet`, `sites.parquet`, `generators.parquet`.

> **Note:** no k-notation conversion and no annual rescaling. Both belonged to the v1 dataset and are wrong here — the values are already exact MWh.

### S1 — Data quality gates

Apply in order, log the count dropped at each step, emit the funnel as a table, and assert it reproduces Section 4:

1. drop `hybrid == "Hybrid"`
2. require lat and lon
3. require `mwdc` present and > 0
4. require `op_year` present
5. require `dcac` within [1.05, 1.65] — catches filing errors
6. validate the name join: reported AC capacity within 10% of `site_master.mwac`. All 508 sites where an independent capacity existed matched within 2%, so this should be a no-op — assert it, do not trust it.

Month-level gates:

- scoreable iff `month >= COD + 6 months` (commissioning ramp)
- scoreable iff the site-year has >= 6 scoreable months
- 2022 gap handling per Section 4 item 1

Do NOT drop a plant for a mid-year COD. Score its post-COD months.

### S2 — Irradiance pull (runs OUTSIDE the agent sandbox)

Per Section 5. `developer.nlr.gov`, PSM v4 GOES Aggregated, CSV endpoint, one request per (grid cell, year). Cache, dedupe on grid cell, resume. Explicitly set `utc=false` and `leap_day=true` — both API defaults are wrong for this pipeline. **2019–2025 only; NSRDB has no 2026** (Section 0.7).

**This stage is a standalone batch job, not part of the agent run.** 33,586 requests at 1/second with a 10,000/day cap is four days minimum. Write it as a self-contained script with a preflight check and a `--dry-run`, hand it to a machine with plain internet access, and let every other stage read the resulting cache offline. If the agent sandbox blocks `developer.nlr.gov` — it does by default — that is an allowlist change, not a code change. See Section 5.

Everything downstream of S2 must run with **no network access at all**. If any stage other than S2 makes an outbound request, that is a bug.

### S3 — Hourly model, summed to month

> **The model runs hourly. The metric is monthly. Not optional.**

Clipping is a hard `min()` against AC capacity and temperature loss multiplies a varying base. Both are non-linear, so by Jensen's inequality feeding a monthly average irradiance into the chain is systematically wrong — it **overstates** output, most for high DC:AC plants, because averaging hides exactly the peaks that would have clipped.

For each hour h:

**a.** Solar position from lat, lon, timestamp.

**b.** Plane-of-array irradiance:

| Tracking | Treatment |
|---|---|
| single-axis | compute rotation angle first, **with backtracking** |
| fixed tilt | use reported tilt and azimuth |
| dual-axis | normal incidence |
| Unknown / Mixed | documented default, site flagged, excluded from headline fleet statements |

```
H_poa = f_transposition(GHI, DNI, DHI, surface_tilt, surface_azimuth, albedo)
```

**c.** Cell temperature — pvlib Faiman model with its documented defaults:

```
T_cell = T_air + H_poa / (U0 + U1 * v_wind)
```

**d.** DC then AC with clipping:

```
P_dc = P_dc_i(m) * (H_poa/1000) * (1 + gamma*(T_cell - 25)) * L * (1 - d)^a
P_ac = min(P_dc * eta_inv, P_ac_i)
```

`P_dc_i(m)` is TIME-VARYING (S4a), not a constant. `a` is plant age in years at that month.

Then `E_exp(i,m) = sum of P_ac over the hours in month m`.

Also persist per month: `clipped_hours`, `mean_cell_temp_c`, `poa_kwh_m2`. All three are diagnostics you will want when a PI looks wrong.

### S4 — Indices

**a. Time-varying DC capacity**, before anything divides by capacity:

```
P_dc_i(m) = sum over generators g at plant i of
            dc_net_capacity_mw_g * 1[COD_g <= m]
```

257 scoreable sites are phased builds. A constant final capacity makes early months look underperforming when the panels were not built yet. Use `P_dc_i(m)` everywhere `P_dc` appears — specific yield, expected generation, and the peer comparison.

**b. PI** = `E_act(i,m) / E_exp(i,m)`

Null for every 2026 month — no irradiance exists, so no expected generation (Section 0.7). Do not substitute a clear-sky estimate silently.

Under Track A this is ABSOLUTE. "This plant lost 15%" stands without reference to any other plant. That is why the NSRDB path was specified.

**c. PR_T** = `E_act / ( P_dc * sum_h[ (H_poa/1000) * (1 + gamma*(T_cell-25)) ] )`

IEC 61724-1. The temperature correction sits INSIDE the irradiance-weighted sum, never applied to a monthly average.

**d. SY** = `E_act(i,m) / P_dc_i(m)` — MWh per MWdc

Normalise by DC, never AC. Two plants at 100 MWac with DC:AC of 1.20 and 1.45 show ~20% different AC capacity factors while both perfectly healthy.

**e. Peer set**

```
P_i = { j != i : haversine d_ij <= R, same tracking type,
        |age_j - age_i| <= 4, |dcac_j - dcac_i| <= 0.20 }
```

Expand R through 150, 250, 400, 600 km until at least 15 peers. **Record the radius used** — it is a confidence flag and belongs in the interface. Fewer than 4 peers: no PRI, fall back to PI alone, mark it.

With 6,204 sites a naive all-pairs distance is 38M pairs per month. Build a BallTree on radians with the haversine metric once, and query it.

**f. Peer health filter — do not skip**

```
P_health(i,m) = { j in P_i : PI(j,m) >= 0.85 }
```

For 2026 there is no PI, so screen peers on their **2025 mean PI** carried forward and tag `peer_health_carried_forward = TRUE`. Never skip the filter outright.

A sick reference inverts the comparison. In testing a healthy plant scored PRI 2.23 in December purely because its single reference had collapsed. Sick plants cluster geographically — shared O&M contractor, shared weather, shared module batch — so contamination is likelier than chance suggests.

**g. PRI** = `SY(i,m) / median( SY(j,m) for j in P_health(i,m) )`

MEDIAN, not mean. Robust to a peer the health filter missed.

### S5 — Decision matrix

| | **PI < 0.92** | **PI >= 0.92** |
|---|---|---|
| **PRI < 0.92** | **LEAD.** Plant-specific and asset-side. Classify and quote. | Peer group broken or mis-matched. Re-check peers before acting. |
| **PRI >= 0.92** | Regional: weather year, curtailment or model bias. **Not a lead.** | Healthy. No action. |

Require BOTH indices to flag AND at least 2 fault months before a site becomes a lead.

### S6 — Fault signature — the D-Band Method

> **Run order: S6 depends on S7.** One discriminator (DEGRADATION +2) needs the Part 6 trajectory slope, so run S7 before S6 despite the numbering. The numbering follows the methodology's parts, not execution order.

#### The deficit

```
score(i,m) = PRI(i,m)                     where a valid peer group exists
           = seasonally-calibrated PI      otherwise  (Section 0.1)
D(i,m)     = max(0, 1 - score(i,m))
```

Record `benchmark_mode` as "peer" or "physical" per site-month. Step 5 uses it. **Note this is NOT `1 - PI`.** The primary benchmark is the peer group.

#### Step 1 — Elimination gates

Run BEFORE any fault attribution. First hit wins, and each STOPS classification with recovery 0%.

**G1 REGIONAL → CURTAILMENT**
- BA-month fleet median score < 0.92
- AND \|site score − BA median score\| <= 0.10
- AND >= 3 scoreable plants in that BA-month

Compute the BA-month median over scoreable plants only, and compute it for every BA-month BEFORE classifying any site, since every site in the BA needs the same reference number.

**G2 WINTER → SNOW**
- latitude >= 37 AND month in {Nov, Dec, Jan, Feb, Mar}
- AND mean(score over Apr–Oct of that year) >= 0.95
- 2026 handling per Section 0.6

**G3 DESIGN → CLIPPING**
- DC:AC >= 1.35 AND month in {Apr..Aug} AND PRI >= 0.95
- Note this tests PRI specifically, not score, so it needs a peer group. Skip G3 where `benchmark_mode` is "physical".

No gate fires → the deficit is asset-side. Continue.

#### Step 2 — Band to candidate set

| D band | Candidates | Typical read |
|---|---|---|
| 0.00 – 0.03 | NOISE | within peer scatter |
| 0.03 – 0.08 | DEGRADATION / SOILING(early) | watch, do not call |
| 0.08 – 0.15 | SOILING > BLOCK(1/12, 1/10) > DEGRADATION > TRACKER > BOS | most common fault band |
| 0.15 – 0.30 | BLOCK(1/8..1/4) > BOS > TRACKER > SOILING(severe) | highest $ per lead |
| 0.30 – 0.50 | BLOCK(1/3, 1/2) > BOS(severe) | major, usually visible in SCADA already |
| 0.50 – 0.70 | BLOCK(1/2) > partial OUTAGE | half the plant is down |
| 0.70 – 1.00 | OUTAGE_FULL | plant is off |

The band ranks likelihood; it does not decide. Step 4 decides.

#### Step 3 — Block fraction lookup (sizing only, never causation)

| D | Fraction | D | Fraction | D | Fraction |
|---|---|---|---|---|---|
| 0.042 | 1/24 | 0.167 | 1/6 | 0.375 | 3/8 |
| 0.050 | 1/20 | 0.200 | 1/5 | 0.400 | 2/5 |
| 0.063 | 1/16 | 0.222 | 2/9 | 0.417 | 5/12 |
| 0.083 | 1/12 | 0.250 | 1/4 | 0.500 | 1/2 |
| 0.100 | 1/10 | 0.286 | 2/7 | 0.667 | 2/3 |
| 0.111 | 1/9 | 0.300 | 3/10 | 0.750 | 3/4 |
| 0.125 | 1/8 | 0.333 | 1/3 | | |
| 0.143 | 1/7 | | | | |

> **Guard, from the tracker itself:** a fraction match alone is NOT a block outage. The run must ALSO be flat (std of D across the run < 0.05) AND start with a step (D rises >= 0.08 from the prior month). Random deficits land on these values by chance roughly 30% of the time. Shape confirms the CAUSE; the fraction then gives the SIZE. Never the other way round.

Ambiguity handling per Section 0.5 — nearest match, record `n_candidates`.

#### Step 4 — Discriminators

Score every test, sum by signature, highest total wins. Scope per Section 0.4.

| Test | Points to | |
|---|---|---|
| D flat >= 2 months (std < 0.05) AND matches 1/N | BLOCK | +3 |
| Step onset: D jumps >= 0.08 from prior month, holds | BLOCK | +2 |
| D rises monotonically >= 3 months, total rise >= 0.06 | SOILING | +3 |
| D falls >= 0.05 the month after that rise | SOILING | +2 |
| corr(D, daylight hours) >= 0.50 across the year | TRACKER | +3 |
| Single-axis tracking | TRACKER | +1 |
| D >= 0.05 in >= 8 months AND CV(D) < 0.35 | DEGRADATION | +3 |
| Year-on-year PI declining > 1.5%/yr (S7 trajectory) | DEGRADATION | +2 |
| CV(monthly D) >= 0.50, no seasonal or step pattern | BOS | +3 |
| >= 2 NON-consecutive months with D >= 0.15 | BOS | +2 |
| D >= 0.70 in any single month | OUTAGE | +5 |

Tie-break: `OUTAGE > BLOCK > SOILING > TRACKER > DEGRADATION > BOS`

Winning total < 3 → UNATTRIBUTED. In practice only a +3 or +5 test can reach 3, since no signature's supporting tests sum to 3 on their own — so "no primary test fired" and "winning total < 3" are the same condition.

**Persist the full per-signature score vector, not just the winner.** The explorer must be able to show why a call was made and what came second.

#### Step 5 — Confidence

| Level | Test |
|---|---|
| HIGH | winning score >= 5 AND >= 8 healthy peers AND >= 2 yrs history |
| MEDIUM | winning score 3–4 AND >= 4 healthy peers |
| LOW | winning score < 3, OR < 4 peers, OR single year of data |

Downgrade ONE level if any of:

- phased build with capacity added inside the window (257 sites)
- < 6 scored months in the year
- COD within 6 months of the affected month (commissioning ramp)
- `benchmark_mode` was "physical" rather than "peer"

A LOW result is **relabelled to UNATTRIBUTED** (recovery 35%) and routed to full diagnostic. It does not keep its provisional signature. Persist both `signature_raw` and `signature_final` so the relabelling is auditable.

#### Step 6 — Action map

Recovery fractions match methodology Part 8 exactly; the inspection and preventative columns are new and belong in the explorer.

| Signature | REC% | Inspection | Preventative? |
|---|---|---|---|
| OUTAGE_FULL | 90% | SCADA + substation service | NO — infant mortality |
| BLOCK_OUTAGE | 90% | String/combiner IV + inverter | YES — wear-out |
| SOILING | 85% | Soiling station + clean trial | YES — schedule |
| TRACKER | 80% | Alignment survey + controller | NO — infant mortality |
| BOS_INTERMITTENT | 70% | Aerial IR + string IV trace | YES — wear-out |
| DEGRADATION | 30% | EL imaging + IV + PID test | NO — capex cycle |
| UNATTRIBUTED | 35% | Full site diagnostic | — |
| CURTAILMENT | 0% | none — commercial | — |
| SNOW | 0% | none — weather | — |
| CLIPPING | 0% | none — design | — |

Preventative replacement is rational ONLY for wear-out faults. For infant-mortality faults the answer is commissioning QA and warranty enforcement — replacing the part resets you to the high-risk end of the curve and makes things worse. Carry the PREVENTATIVE column into S8h so the maintenance rule cannot recommend replacing an infant-mortality part.

#### Output per site-month

`signature_final`, `signature_raw`, `D`, `score`, `benchmark_mode`, `gate_fired`, `band`, `block_fraction`, `n_candidates`, `score_vector` (all six), `confidence`, `downgrade_reasons`, `fault_flag`, `classifier_version`.

### S7 — Trajectory (Part 6)

**a.** `tau(i,m) = (m - COD_i) / 365.25`, years since COD.

**b.** Remove the shared weather signal, then fit:

```
PI_adj(i,m)     = PI(i,m) / median over region r of PI(j,m)
ln PI_adj(i,m)  = alpha_i + beta_i * tau(i,m) + eps
```

Report beta with standard error and t-statistic. Gate on `years_present`: fit at 2+, mark decision-grade only at 4+.

**c. Excess degradation**, the decision variable: `beta_excess = beta + d`

| beta | Reading |
|---|---|
| approx −0.5%/yr | normal structural degradation, healthy |
| −1% to −3%/yr | mild deterioration, monitor |
| < −3%/yr | accelerating loss, investigate, especially if young |
| > +3%/yr | **IMPROVING** — repaired, or ramp completing. Remove from the call list. |

**d. Envelope / gap decomposition**

```
envelope E_i(m) = 0.95 quantile of PI_adj over the trailing 12 months
gap      g_i(m) = E_i(m) - PI_adj(i,m)
fit beta_struct from ln E_i(m), beta_gap from g_i(m)
```

- `beta_struct < -1.5%/yr` → fast structural degradation (hardware)
- `beta_gap > 0` → operational gap widening (O&M)

The quadrant is the sale:

| | **Gap narrowing** | **Gap widening** |
|---|---|---|
| **Slow degradation** | healthy, no action | **O&M deterioration — best lead** |
| **Fast degradation** | hardware but managed — warranty claim | distressed — impairment / DSCR risk |

Needs 12 months of trailing data. Do not compute it on less.

**e. Warranty clock:** `W_i = warranty_term - tau(i,m)`, years of cover remaining.

Defaults, ASSUMED not contractual: 2y EPC workmanship, 5–10y inverter, 10–12y module product, 25y module performance.

Flag `W_i < 6 months` as warranty-urgent; it outranks ticket size. A fault at month 22 of a 24-month warranty is a deadline with a third party paying, not a repair quote — the strongest cold-outreach trigger the model produces, and a CFO conversation rather than an asset-management one. Every warranty output carries the caveat that terms are defaults that indicate where to ask, not that cover exists.

> **Identification warning — encode it, do not just read it.**
> `age = period - cohort`. Degradation with age, build quality of a commissioning cohort, and calendar-period weather are perfectly linearly dependent. All three linear trends CANNOT be jointly identified. Resolution: FIX `d` at the IEC/lab prior from the config and let vintage absorb the residual. Never run an unconstrained regression and report its degradation estimate — it will return a confident number that is partly a vintage effect.
>
> With 6+ years on 2,922 sites, vintage cohort effects are now estimable as a stepwise cohort term. Estimate them THAT way — stepwise by COD band, with degradation still fixed — not by relaxing the constraint.

### S8 — Event ledger and hazard model (Part 7) — now fully buildable

**a. Duration and incidence**

```
D(i,y,s) = count of months in year y with signature s
K(i,y,s) = number of maximal runs of consecutive months with signature s,
           WITH A ONE-MONTH GAP TOLERANCE
```

A five-month block outage is ONE event lasting five months, not five events. Conflating them corrupts every rate model downstream.

A missing month (2022 gap, pre-COD, coverage gap) must NEITHER break a run NOR extend one. Treat it as absent from the sequence, not as a recovery.

**b. Three ledgers, never mixed**

| Ledger | Signatures | Modelled as |
|---|---|---|
| **Fault** | OUTAGE_FULL, BLOCK_OUTAGE, SOILING, TRACKER, BOS_INTERMITTENT, UNATTRIBUTED | hazard model |
| **Exposure** | CURTAILMENT, SNOW, CLIPPING | site characteristics — properties of WHERE the plant is, not how well it was built. Still forecast, never counted as unreliability. |
| **State** | DEGRADATION | S7 trajectory; excluded from the incidence model (it runs ~11 months by construction because it is a chronic state, not an event) |

**c. Schema**, one row per site x year x signature:

```
site, year, signature, months, episodes, exposure_months, age_start,
mwh_lost, usd_lost, max_severity
```

`exposure_months` is the denominator and MUST be explicit. Never assume 12. Sites enter mid-year at COD, months drop for data quality, 2026 caps at 5. A site with 7 scored months and 1 episode has DOUBLE the rate of one with 14 months and 1 episode.

**d. Hazard shape** per signature — `h_s(a) = (k_s/eta_s) * (a/eta_s)^(k_s - 1)`

| k_s | Hazard | Failure mode | Intervention |
|---|---|---|---|
| < 1 | decreasing | infant mortality: workmanship, commissioning | commissioning QA, warranty claim |
| ~ 1 | constant | random / external | insurance, spares holding |
| > 1 | increasing | wear-out: fatigue, corrosion, connector ageing | scheduled preventative replacement |

The reference dataset showed OUTAGE_FULL and TRACKER with textbook infant mortality, BLOCK_OUTAGE and BOS_INTERMITTENT rising monotonically with age, and SOILING flat with age (climate-driven — model it on LOCATION, not age). Check whether this panel reproduces that. If it does, that is meaningful evidence the classifier is not producing noise. If it does not, suspect the classifier before suspecting the physics.

Watch for survivor bias at 9+ years: chronically bad plants get repaired, repowered or retired and leave the panel. Handle with left-truncation, not by taking the late-life fall at face value.

**e. Rate model**, one per signature, over all site-years:

```
log E[K_iys] = log E_iy + alpha_s + f_s(age) + beta_s' x_i + log u_i
```

`log E_iy` is the OFFSET, not a coefficient. `x_i`: climate region, tracking, DC:AC, module technology, capacity, BA, vintage cohort, latitude, elevation. `u_i`: **frailty**, a site-level random effect for inherent reliability.

**Use negative binomial, not Poisson.** Fault counts are strongly over-dispersed — the reference dataset showed Var/mean = 3.24. Poisson assumes 1.0, and at 3.24 it reports intervals about 1.8x too narrow: a stated 90% interval that is really about 60%. The excess variance is real signal — some sites are genuinely accident-prone — and the frailty term captures exactly that. Site reliability is itself a predictor. **Compute and report Var/mean on THIS panel.** If it is near 1, say so.

For climate-driven signatures (soiling, snow) replace the age term with spatial smoothing:

```
lambda_j = sum_i w_ij K_i / sum_i w_ij E_i,   w_ij = exp(-d_ij^2 / 2h^2)
```

**f. Credibility shrinkage** for young assets:

```
lambda_j = Z_j * (K_j/E_j) + (1 - Z_j) * lambda_pool,   Z_j = E_j/(E_j + tau_s)
tau_s    = E[Var(K|i)] / Var(E[K|i])
```

This is now estimable — it needs a long panel and there is one. Hierarchical pool, most specific group with enough data:

| Level | Pool | Use when |
|---|---|---|
| 1 | nearest peers within R km, same tracking and technology | >= 200 plant-months available |
| 2 | same climate region + tracking type | level 1 too thin |
| 3 | same balancing authority | location-driven signatures |
| 4 | whole fleet, age-adjusted | fallback |

**g. Probability and expected loss** over the next 12 months:

```
P_js(12mo) = 1 - (1 + lambda_js*12/phi)^(-phi)        negative binomial
EAL_js     = (lambda_js*12) * L_bar_s * delta_bar_s
             * (P_dc_j * SY_bar_j / 12) * PPA
EAL_j      = sum over s
```

Report the COMPONENTS, not just the total. "62% chance of a block outage, typically 1.9 months, typically 12% deficit" is actionable; a single risk score is not. The interface must show the components.

**h. Preventative maintenance rule:** act if `EAL_js * rho_s * H > C_prev_js`

Two modifiers change the answer materially. **Warranty:** inside a live window the owner's cost is near zero and the rule becomes "act if the deadline is near". **Hazard shape:** preventative replacement is only rational for wear-out faults (`k_s > 1`). Replacing a component with DECREASING hazard makes things worse — you reset to the high-risk part of the curve.

**i. Validation — mandatory before any predictive claim.**

Fit on years <= Y, predict Y+1. With 8 years you can backtest several folds — do it, and report each.

| Test | Method | Pass criterion |
|---|---|---|
| Calibration | predicted vs observed by decile of lambda | slope ~1, intercept ~0 |
| Discrimination | AUC for ">= 1 episode next year" | > 0.65 to be useful |
| Over-dispersion | Pearson chi2 / df on held-out data | ~1 |
| Baseline | vs "predict the fleet mean rate" | must beat it materially, or the covariates add nothing |

Calibration matters more than discrimination. A model that ranks correctly but says 40% when the truth is 12% destroys credibility the first time a CFO tracks the outcome.

Cluster standard errors by BA-year and by module supplier where known. Failures are correlated, not independent — shared O&M contractors, module batches and regional weather cause simultaneous failures.

### S9 — Index to dollars (Part 8)

**a.** `T(i,m) = median(SY_j over healthy peers) * PRI_P75 * P_dc_i(m)`

Compute `PRI_P75` as the 0.75 quantile of PRI across THIS fleet. Why P75: 25% of comparable plants — same tracking, same age, same weather — already achieve it, so it is demonstrably attainable and survives scrutiny in a proposal. The median is too soft and understates the opportunity; P90 invites argument.

No peer group: `T(i,m) = E_exp(i,m) * PI_P75`.

**b.** `G(i,m) = max(T(i,m) - E_act(i,m), 0)`

**c.** `R(i,m) = G(i,m) * rho_s` — needs S6

**d.** `$(i,m) = R(i,m) * 40.0`

| Signature | rho | Signature | rho |
|---|---|---|---|
| Full outage | 0.90 | Degradation | 0.30 |
| Block outage | 0.90 | Unattributed | 0.35 |
| Soiling | 0.85 | **CURTAILMENT** | **0.00** |
| Tracker | 0.80 | **SNOW** | **0.00** |
| BOS / intermittent | 0.70 | **CLIPPING** | **0.00** |

> **The three zeros are the credibility guardrail.** They are real deficits that must NEVER be sold as recoverable. Unit-test that they stay zero. A future edit that quietly makes curtailment recoverable is the single most damaging change anyone could make to this pipeline.

Every rho is a PLACEHOLDER with no ground truth. Tag accordingly.

**e. Cross-check** against the tracker's quick estimate (Section 0.2):

```
value_usd_quick = D x SY_peer_median x P_dc x REC% x PPA
```

Worked example from the tracker, use it as a unit test:

```
D = 0.25, SY_peer = 150, DC = 500 MW, BLOCK (90%), PPA = 40
-> 0.25 x 150 x 500 x 0.90 x 40 = 675,000 USD for that month
```

Part 8 remains authoritative and ranks the call list. Assert the two stay within 15% of each other; a wider gap points at a peer-set problem.

### S10 — Conviction tiers

| Tier | Test | Meaning |
|---|---|---|
| **Chronic** | flagged this year AND mean PI < 0.92 in prior years | structural, highest conviction, call first |
| **Event** | prior years healthy, this year flagged | recent discrete failure, highest urgency, often still inside EPC warranty |
| **New** | one year of data only | unverifiable — 126 sites |
| **Improving** | beta > +3%/yr | remove from the call list |
| **Warranty-urgent** | any tier with W_i < 6 months | contact first regardless of ticket size |
| **At-risk** | no current fault but EAL in the top decile of peers | sell a maintenance plan, not an inspection. **Now buildable.** |

---

## Section 8 — The explorer interface

*(Phase 3 — first-class deliverable)*

**Purpose.** Carlos needs to move through every flagged site one at a time, see why it was flagged, judge whether he believes it, and record a decision. The interface is how the analysis gets used, not a report on it.

**Form.** A single self-contained HTML file, `explorer.html`, opened by double-click. No server, no build step, no network. Data embedded as JSON in a script tag.

> **Critical:** `fetch()` against `file://` is blocked by the browser. If you split the data into sidecar files, double-clicking the HTML silently shows nothing. So: embed. Budget the payload at 25 MB. To stay inside it, store monthly series as parallel arrays of rounded numbers (PI and PRI to 3 decimals, MWh to integer), not as arrays of objects — that alone cuts the payload roughly 5x. If it still exceeds 25 MB after that, shard per-site detail into JSON files, emit a `serve.sh` running `python -m http.server`, and say plainly in the README that the explorer needs it.

Vanilla JS or a single bundled library. No framework build step, no CDN.

Three views, with a persistent filter bar across all of them.

### View 1 — Fleet overview

- KPI strip: scoreable sites, GWac, site-months scored, leads, high-conviction targets, total recoverable MWh/yr, total recoverable USD/yr at 40/MWh.
- The gate funnel from Section 4, as a funnel or waterfall, with counts and GWac at each step. It answers "what did you throw away and why" before anyone asks.
- Distribution of PI and of PRI, with the 0.92 thresholds marked.
- Fault counts by signature (bar) and by year (stacked bar).
- A US map, sites plotted at lat/lon, coloured by conviction tier or by latest PI, sized by MWac. Clicking a point goes to that site.
- Hazard curves by signature: fault rate against age band.

### View 2 — Triage list

- Every scoreable site, sortable on any column, default sorted by recoverable USD descending.
- **Must be virtualised.** 6,204 rows in the DOM will not scroll acceptably.
- Columns: site, state, operator, MWac, MWdc, DC/AC, tracking, COD, years of data, latest PI, latest PRI, latest D, beta and its t-stat, fault months, episode count, top signature, classifier confidence, recoverable MWh/yr, USD/yr, conviction tier, warranty status, peer count and radius, data-quality flags.
- Filters (persisting across views): year, state, BA, tracking, module, capacity band, conviction tier, signature, PI and PRI ranges, years-of-data minimum, classifier confidence, benchmark mode, "has 2022 gap", "no asset match", "peers < 4".
- Free-text search on site and operator.
- Export the current filtered view to CSV.
- Row click opens View 3.

### View 3 — Site detail

*This is where the work actually happens.*

- **Header:** name, operator, utility, state, county, BA, plant id, MWac, MWdc, DC/AC, tracking, module, tilt, azimuth, COD (month and year), age, generator count, warranty status.
- **Monthly chart**, 2019-01 to 2026-05 on one continuous axis: actual MWh and expected MWh as lines or bars, with PI and PRI on a secondary axis, and the 0.92 threshold drawn. Missing months rendered as GAPS, never as zero — the 2022 hole must look like a hole.
- **Fault ribbon** under the chart: one cell per month, coloured by signature, grey for not-scored with the reason on hover. Hover also shows D, the band, which gate fired if any, the full per-signature score vector, the winning total, the runner-up, the confidence and any downgrade reasons. This is the "why was this called" panel — if Carlos cannot see the second-place signature and the margin, he cannot judge whether to believe the first.
- **Trajectory panel:** PI_adj against tau with the fitted line and its confidence band, beta, SE, t-stat, beta_excess, and the envelope/gap decomposition with the quadrant it lands in.
- **Event ledger table** for this site: year x signature x months x episodes x exposure_months x mwh_lost x usd_lost x max_severity.
- **Peer panel:** the peers used, distance, radius that was needed, how many survived the health filter. Anyone challenging a PRI will ask this first.
- **Recoverable revenue** by month and by signature, with rho shown per row so it is obvious where the number comes from, plus the Part 8 figure and the tracker quick estimate side by side.
- Where BLOCK_OUTAGE is called, show the fitted fraction and `n_candidates`, with the fraction presented as indicative sizing. Never render "1 of 10" as though the inverter count were known.
- **Risk panel:** per signature, probability over 12 months, mean duration, mean deficit, EAL, and the credibility weight Z that was applied.
- **Data-quality notes** specific to this site: missing years, partial 2026, no asset match, unknown tracking, fewer than 4 peers.

### Navigation — the "go through each of them" requirement

- Previous / next through the CURRENT filtered and sorted list, so the order Carlos is working is the order he moves in.
- Keyboard: `j` / `k` or arrows to move, Enter to open, Esc back to the list.
- Deep links: `#site=<id>` so a specific site can be pasted into an email.
- Position indicator: "site 37 of 214 in this filter".

### Triage state — persist it

- Per site: unreviewed / call / dismissed / needs-data, plus a free-text note.
- Persist to `localStorage` keyed by site id, and offer "export decisions to CSV" and "import decisions from CSV" so the state survives a rebuild and can be shared. Show progress: "reviewed 41 of 214".

### Standing caveats — visible, not buried

Every dollar figure in the interface carries, adjacent or in a fixed footer: **a ranking signal, not a quote.** They become defensible only once satellite irradiance replaces climate assumptions (this pipeline does that), ISO curtailment is netted out (it is not), and repair costs come from vendor quotes (they do not). An Assumptions panel lists every constant used, its value, and whether it is measured, assumed or provisional — including the 40 USD/MWh PPA and the classifier status.

---

## Section 9 — Other outputs

| Artifact | Contents |
|---|---|
| `site_month_metrics.parquet` | site, year, month, month_start, E_act, E_exp, PI, PR_T, SY, PRI, peer_count, peer_radius_km, peers_healthy, poa_kwh_m2, clipped_hours, mean_cell_temp_c, scoreable_flag, exclusion_reason, signature, classifier_version, T_target, gross_gap_mwh, recoverable_mwh, value_usd |
| `site_year_summary.parquet` | site, year, months_scored, exposure_months, mean_PI, mean_PRI, min_PI, lead_flag, fault_months, episode_count, top_signature, conviction_tier, beta, beta_se, beta_t, beta_excess, beta_struct, beta_gap, warranty_years_remaining, recoverable_mwh, value_usd |
| `event_ledger.parquet` | schema per S8c |
| `risk_forecast.parquet` | site, signature, lambda, P12mo, mean_duration, mean_deficit, EAL_usd, credibility_Z, pool_level |
| `peer_sets.parquet` | site, year, month, peer_site, distance_km, included_after_health_filter — keep it, it is how you defend a PRI |
| `nsrdb_cache/` | grid_lat= / grid_lon= / year= parquet partitions |
| `PI_PRI_Results.xlsx` | Call List (ranked), Site Detail, Monthly Metrics, Event Ledger, Risk Forecast, Assumptions, Funnel, Notes |
| `run_report.md` | the funnel with counts at every gate, every assumption and its value, every site excluded and why, NSRDB pull statistics, backtest results, and a plain list of what was NOT computed and why |

---

## Section 10 — Acceptance tests

Write these as tests, not as things to eyeball once.

1. **Null handling:** no month with `reported == False` becomes 0 anywhere. Assert the null count end to end.
2. **Missing-year handling:** a site absent from a year produces NO rows and NO fault. Regression-test a site present in 2021 and 2023 but absent in 2022 — it must not generate an outage episode, and its 2022 must not count toward `exposure_months`.
3. **Episode runs:** a missing month neither breaks nor extends a run. Test both.
4. **Hourly not monthly:** run the chain once on monthly-mean irradiance for a high DC:AC site and confirm it OVERSTATES relative to the hourly run. Confirms the Jensen argument holds in your implementation.
5. Column P equals column Z on every workbook row (P is the month sum, Z the EIA annual total).
6. **Time-varying capacity:** on the 257 phased sites `P_dc(m)` is non-decreasing and equals `site_master.mwdc` at the last month.
7. **Peer health:** no peer with PI < 0.85 appears in any peer median.
8. **Peer minimum:** PRI is null wherever `peer_count < 4`, never a number.
9. **Zero recovery:** rho for CURTAILMENT, SNOW and CLIPPING is exactly 0.00.
10. **Trajectory gating:** no beta emitted for a site with one year of data; no decision-grade flag below 4 years.
11. **Degradation sanity — the best end-to-end check you have.** The median fitted slope across sites with 4+ years should land near −0.5%/yr against an assumed structural degradation of 0.5%/yr. The method recovering a physical constant it was never given means the pipeline is sound. On the reference dataset this came out at −0.51%/yr. With 4,396 sites at 4+ years the estimate here will be far tighter, so the test is sharper: if the median slope is materially off −0.5%/yr, something upstream is wrong. Suspect timezone handling and the capacity denominator first.
12. **Over-dispersion:** report Var(K)/E[K]. If it is near 1, negative binomial was unnecessary and you should say so rather than defaulting to it silently.
13. **Reconciliation:** total E_act by year matches the eight annual totals in Section 4 exactly.
14. **Explorer:** opens from `file://` with no server, renders the full triage list, next/previous walks the filtered order, and a missing month renders as a gap rather than a zero.
15. **Classifier — gate precedence:** a site-month satisfying both G1 and the OUTAGE band returns CURTAILMENT, not OUTAGE_FULL. Gates run first and stop.
16. **Classifier — D definition:** D is built from PRI where peers exist. Assert no site-month with a valid peer group computed D from PI.
17. **Classifier — zero recovery:** every month labelled CURTAILMENT, SNOW or CLIPPING carries `recoverable_mwh = 0` and `value_usd = 0`. Same guardrail as test 9, checked at the row level this time.
18. **Classifier — block guard:** no month is labelled BLOCK_OUTAGE on a fraction match alone. Assert every BLOCK month belongs to a run that is both flat (std < 0.05) and step-onset (>= 0.08 rise).
19. **Classifier — LOW confidence relabels to UNATTRIBUTED.** Assert no `signature_final` outside {UNATTRIBUTED, the three zero-recovery labels} carries confidence LOW.
20. **Classifier — watch band:** no month with `0.03 <= D < 0.08` contributes an episode, exposure-weighted rate, or dollar.
21. **Classifier — dollar cross-check:** the tracker worked example (D=0.25, SY=150, DC=500, BLOCK, PPA=40) returns 675,000 USD.
22. **Classifier — profile sanity.** Compare the resulting signature mix against the reference frequencies in methodology Part 7 Step E1: UNATTRIBUTED around 0.76 episodes per plant-year, BOS_INTERMITTENT 0.58, SOILING 0.31, BLOCK_OUTAGE 0.29, and mean episode duration near 1.0 months for soiling against 3.93 for tracker faults. A wildly different profile means the classifier is misconfigured, not that this fleet is unusual. Report the comparison in the run report either way.
23. **Classifier — hazard coherence.** The reference data showed OUTAGE_FULL and TRACKER with infant mortality, BLOCK_OUTAGE and BOS_INTERMITTENT rising with age, SOILING flat with age. If this panel reproduces that from 8 years and 6,204 sites, it is strong evidence the classifier is not producing noise. If it does not, suspect the classifier before the physics.
24. **NSRDB domain:** grep the codebase for `nrel.gov` and assert zero hits outside comments. The domain does not resolve; a stale reference fails at DNS with no useful error.
25. **NSRDB timezone:** assert every cached response was requested with `utc=false`. Spot-check one cell — if the irradiance peak sits near 12:00 local, the request was right; if it is offset by the site's UTC offset, every month boundary in the run is wrong.
26. **NSRDB leap day:** assert the 2020 and 2024 caches contain 8,784 hourly rows, not 8,760. The API omits 29 February by default.
27. **2026 handling:** assert PI and PR_T are null for every 2026 month, that no 2026 site-month carries a LEAD flag, and that PRI is still populated where a peer group exists.
28. **Cache completeness:** the count of distinct `(grid_cell, year)` cache partitions equals 4,798 x 7 = 33,586 before S3 is allowed to run. A partial cache silently produces a partial fleet.
29. **Preflight classification:** with an unreachable host, S2 exits non-zero within a few seconds and names the cause as a proxy denial rather than an auth failure. Test it by pointing the base URL at a host that is definitely not allowlisted.
30. **Offline downstream:** run S0, S1, S3 through S11 with networking disabled entirely. They must complete against a warm cache. Any stage that raises a connection error is a bug.
31. **Cache manifest:** S3 refuses to start and names the missing partitions when the cache is incomplete, rather than modelling whatever happens to be present.
32. **No secrets in outputs:** assert the API key string appears in no parquet, no CSV, no log, no cache filename, not in `manifest.json` and not in `explorer.html`.

---

## Section 11 — Open items for Carlos

1. **Confirm the six interpretation defaults in Section 0** — particularly 0.1 (what "seasonally-calibrated PI" means under Track A) and 0.2 (which of the two dollar formulas ranks the call list). Both change reported numbers. Everything is implemented and running under the defaults meanwhile.
2. **Re-pull EIA-923 for 2022 from the same source as the other years.** The file supplied on 11 August 2026 (`PV_Solar_22_data.xlsx`) was byte-identical to the 2022 already in the panel — the same 224 plants and the same 12,961,245 MWh — so the gap is still open. Its 71-column Grossgen layout differs from the 97-column layout of every other year, which is the tell: it came from a different EIA page or schedule. This is the only gap left in an otherwise complete eight-year panel and it sits in the middle, where it does most damage to trajectory fits.
3. **Allowlist `developer.nlr.gov` for the agent environment, or decide the pull runs elsewhere.** The sandbox proxy currently rejects the CONNECT tunnel with 403 before any request is sent. For the Claude Code CLI this is `sandbox.network.allowedDomains` in settings; for a managed or hosted session an administrator sets it under Organization Settings → Capabilities → Code execution. Recommendation: do both — allowlist the host so ad-hoc checks work, but run the four-day pull on a normal machine regardless. Section 5 has the host list and the config shapes.
4. **Rotate the NLR API key.** The key issued on 11 August 2026 was shared in plain text over chat, so treat it as compromised: reissue at `https://developer.nlr.gov/signup/`, put the new one in `NLR_API_KEY`, and never paste a key into a document, ticket or message again.
5. **Re-run 2026 once NSRDB publishes it.** PSM v4 currently stops at 2025, so 2026 is PRI-only. Watch `https://nsrdb.nlr.gov/about/announcements`; the 2025 data landed as an announcement there. Adding the year should be a re-run, not a rewrite.
6. **ISO curtailment feeds** (CAISO, ERCOT). Now the largest remaining source of false positives — curtailed plants read as faulty and CURTAILMENT carries rho = 0.00, so misclassification moves real money.
7. **Ground truth on 10–20 known outcomes.** Still the only way to tune rho_s, the classifier thresholds and the ledger. Until then the dollar figures stay a ranking signal.
8. **Confirm the scored window.** Recommendation: score 2019–2026, flag 2022 and 2026 as partial, and exclude both from fleet-level statements.

---

## Section 12 — Repo layout and run order

| File | Purpose |
|---|---|
| `config.py` | all constants, thresholds, PPA = 40.0, warranty terms |
| `s0_load.py` | CSVs → parquet, COD construction |
| `s1_gates.py` | data quality funnel, logged and asserted |
| `s2_nsrdb.py` | **standalone batch job, runs outside the agent.** Cached, resumable, grid-deduplicated pull against `developer.nlr.gov`, PSM v4. Preflight + `--dry-run`. No imports from the rest of the repo. |
| `s3_model.py` | hourly pvlib chain → monthly expected |
| `s4_indices.py` | PI, PR_T, SY, peers (BallTree), PRI |
| `s5_decision.py` | lead matrix |
| `s6_signatures.py` | D-Band classifier: gates, bands, discriminators, confidence, relabelling. **Runs after s7** — one discriminator needs the trajectory slope. |
| `s7_trajectory.py` | slopes, envelope/gap, warranty clock |
| `s8_ledger.py` | duration, incidence, hazard, frailty, credibility, EAL |
| `s9_dollars.py` | target, gap, recoverable, value |
| `s10_report.py` | parquet + Excel + `run_report.md` |
| `s11_explorer.py` | builds `explorer.html` with embedded JSON |
| `tests/` | Section 10 |

**S2 is out of band.** Run it once, anywhere with internet, before or in parallel with everything else. The rest of the pipeline treats its cache as a static input and runs fully offline.

**Execution order** (not the same as the numbering):

```
S0 -> S1 -> S2 -> S3 -> S4 -> S5 -> S7 -> S6 -> S8 -> S9 -> S10 -> S11
```

S7 precedes S6 because the DEGRADATION discriminator consumes the trajectory slope. Within S6, the BA-month median scores for gate G1 must be computed for the whole fleet before any individual site is classified.

**Build order.** Get S0–S5 and S7 running on a stratified 100-site subsample first, with the NSRDB cache warm for just those sites. Validate test 11 (the degradation sanity check) on that subsample before committing to a 33,586 cell-year pull that will take at least four days at the NLR rate limit. Then run S6 on the subsample and check tests 15–23 — the profile sanity check in test 22 is the cheapest way to catch a misconfigured classifier before it has scored 330,754 site-months. Then scale up, then S8–S9, then the explorer.
