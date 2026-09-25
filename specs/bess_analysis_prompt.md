# Claude Code Prompt — BESS Fleet Health, Efficiency & Reliability Analysis
**Version 2** — adds the auxiliary-load decomposition, C-rate/duration effects, and a monthly reliability-engineering layer.

> Run: `claude "follow the spec in bess_analysis_prompt.md"`

---

## ROLE AND OBJECTIVE

You are building a battery storage equivalent of a solar underperformance detection engine. **The direct translation does not work, and understanding why is the whole design.**

Solar output is *involuntary*: the sun shines, the plant either converts it or it doesn't, so every shortfall is a fault. Battery output is a *dispatch decision*: a battery that barely cycled in March might be broken, or might correctly have been waiting for price spreads that never came. There is no physical counterfactual, only a commercial one.

So the anchor is not throughput. It is **efficiency** — and specifically, efficiency decomposed into true conversion efficiency and parasitic load, which monthly data can do better than you would expect.

Objective: for every US grid-scale battery, 2019–2025, compute **monthly** efficiency, availability and utilisation metrics; separate technical problems from commercial ones; and produce a ranked list of assets with a genuine health issue.

---

## INPUTS

### Charge and discharge
`/mnt/user-data/uploads/EIA923_Schedules_2_3_4_5_M_12_{2019..2024}_Final*.xlsx`
`/mnt/user-data/uploads/EIA923_Schedules_2_3_4_5_M_12_2025_Early_Release_30JUN2026.xlsx`

Sheet **`Page 1 Energy Storage`** — a dedicated sheet, not the main generation sheet. Header row 6 (row 7 in 2025; detect by searching for `Plant Id`).

Column semantics — get these right, they are not obvious:

| Column | Meaning |
|---|---|
| `Quantity {Month}` | **Charge**, MWh consumed |
| `Grossgen {Month}` | **Discharge**, MWh delivered |
| `Netgen {Month}` | Discharge − charge (negative for most batteries) |

Filter to `Reported Prime Mover == 'BA'` and `Reported Fuel Type Code == 'MWH'`. `PS` is pumped hydro and `FW` is flywheel — separate cohorts, never mixed with lithium.

### Asset characteristics — pull ALL vintages 2019–2025
```
https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip
https://www.eia.gov/electricity/data/eia860/archive/xls/eia860{2019..2024}.zip
```
`3_4_Energy_Storage_Y{yyyy}.xlsx`, tabs `Operable` and `Retired and Canceled`, header row 2. This schedule is unusually rich:

- `Nameplate Energy Capacity (MWh)` — **the denominator for everything**
- `Maximum Charge Rate (MW)`, `Maximum Discharge Rate (MW)` — asymmetry is itself a signal
- `Storage Technology 1..4` — chemistry
- `Storage Enclosure Type` — drives HVAC behaviour
- Applications: `Arbitrage`, `Frequency Regulation`, `Load Following`, `Ramping / Spinning Reserve`, `Co-Located Renewable Firming`, `Transmission and Distribution Deferral`
- `Operating Month`, `Operating Year`

**All vintages is not optional here.** Unlike every other technology, battery energy capacity *grows* over life through contracted augmentation. Build `E_rated[i, year]` as a time-varying series; a single snapshot will read augmentation as fade recovery.

### Ambient temperature — required for the thermal work
Monthly mean dry-bulb per site from NSRDB PSM3 by lat/lon, or NOAA nClimGrid by county.

---

## THE CORE METHOD — auxiliary-load decomposition

This is the most important idea in the spec, and it is not in the published literature for monthly data.

Apparent round-trip efficiency conflates two physically different things: **conversion losses** (cells, busbars, PCS) which scale with throughput, and **parasitic load** (BMS, contactors, fans, HVAC, standby electronics) which runs roughly continuously regardless of cycling. Industry sources note that in lightly-cycled applications parasitic load can roughly halve apparent efficiency over a billing month, and that HVAC alone can swing system RTE by 2–4 percentage points seasonally in hot climates.

Monthly charge and discharge are enough to separate them. For site *i*, month *m* with `h_m` hours:

```
Charge[m] = Discharge[m] / eta + P_aux * h_m
```
Divide through by discharge:
```
Charge[m] / Discharge[m]  =  1/eta  +  P_aux * (h_m / Discharge[m])
```
Regress `y = Charge/Discharge` on `x = h_m/Discharge`, per site, across all its months:

```
intercept a  ->  eta_true = 1/a        # true conversion efficiency
slope     b  ->  P_aux    = b          # parasitic load, MW
```

**Validated on this dataset (607 sites with ≥10 usable months):**

| Quantity | Median | p10 | p90 |
|---|---|---|---|
| `eta_true` (intercept) | **0.889** | 0.775 | 0.956 |
| Naive RTE, same sites | **0.844** | — | — |
| `P_aux` as % of nameplate MW | **0.21%** | −0.07% | 0.85% |

Parasitic load depresses apparent RTE by **4.5 points at the median**. The naive figure (0.844) matches the EIA published fleet average of roughly 82–85%; the decomposed conversion efficiency (0.889) matches the expected cell-plus-PCS figure. Both numbers are right — they are measuring different things, and only the decomposition tells you which one is degrading.

Fit requirements: ≥10 months with `Charge > 0`, `Discharge > 0`, `Charge/Discharge < 3`, and discharge above ~10% of rated energy (exclude near-idle months that dominate the regression). Reject fits with `a <= 0` or `eta_true` outside (0.5, 1.0].

**Fit separately for summer and shoulder months** to isolate HVAC: `P_aux_summer − P_aux_shoulder` is a direct measure of thermal-management load, and a site whose summer excess is growing year on year has a worsening cooling problem.

---

## MONTHLY METRIC STACK

### M1 — Apparent RTE
```
RTE[i,m] = Discharge[i,m] / Charge[i,m]
```
Blank where `Charge <= 0` or outside `(0, 1.2]`. Flag months where `|Discharge − Charge| / Charge > 0.5` as state-of-charge-drift unreliable.

### M2 — Decomposed efficiency (above)
`eta_true[i]`, `P_aux[i]`, `P_aux_summer[i]`, `P_aux_shoulder[i]`, plus rolling 12-month refits to get a trend on each.

### M3 — Duration and C-rate band
```
Duration[i,y] = E_rated[i,y] / Nameplate_MW[i,y]
C_rate_proxy  = 1 / Duration
```
RTE is C-rate dependent: at 1C a pack typically loses 1–3 points against its 0.5C datasheet figure, and more at 2C. **A 1-hour and a 4-hour battery are not comparable on RTE.** Always compare within duration bands: `<1.5h`, `1.5–2.5h`, `2.5–4.5h`, `>4.5h`.

### M4 — Utilisation
```
EFC[i,m] = Discharge[i,m] / E_rated[i,y]              # equivalent full cycles
UTI[i,m] = EFC[i,m] / median(EFC of matched peers, month m)
```
Peer match on **same balancing authority** (price is the BESS weather — peers in the same market faced the same spreads), same duration band, age ±3 years. Peer health filter: drop peers with RTE < 0.75 or zero throughput that month.

### M5 — Availability
```
Full_outage[i,m]   = Charge ~ 0 AND Discharge ~ 0 AND peer median EFC > 0.5
Partial_avail[i,m] = throughput at a quantised fraction (1/N) of the site's trailing
                     6-month median, flat across >=2 months, with a step onset
```

### M6 — Capacity fade
```
EPC[i,m]  = Discharge[i,m] / max(1, round(EFC[i,m]))       # energy per cycle
Fade[i]   = log-linear slope of the 12-month rolling 90th percentile of EPC
```
Needs ≥24 months and ≥0.5 EFC in most months. Below that, output `insufficient_history` rather than a noisy number. **Must be computed against the time-varying `E_rated` or augmentation will mask it.**

### M7 — Charge/discharge asymmetry
```
Asym_rated[i]    = Max_Discharge_MW / Max_Charge_MW
Asym_realised[i] = peak monthly discharge power / peak monthly charge power
```
Realised drifting below rated suggests discharge-side derating.

### M8 — Warranty position
Battery warranties are written against **energy throughput and an operating envelope, not calendar time**. Track:
```
Cum_EFC[i]        = cumulative equivalent full cycles since COD
Throughput_used   = Cum_EFC / contracted cycle life (assume 6,000 if unknown, flag the assumption)
Envelope_breach   = months with mean ambient outside the assumed operating envelope
```
Operating outside the temperature or state-of-charge envelope can void a warranty. Augmentation is planned at financial close rather than discovered later, so a site whose measured capacity is falling ahead of its augmentation schedule is a contractual conversation, not just a technical one.

---

## DECISION MATRIX

| | **eta_true normal (≥0.86)** | **eta_true declining or low** |
|---|---|---|
| **Throughput normal** | Check `P_aux` — if elevated, thermal-management problem | **Cell degradation** — capacity-guarantee territory |
| **Throughput low vs peers** | **Commercial** — strategy, offtake or curtailment. No inspection to sell. | **Availability** — racks or containers offline. The real technical lead. |

The decomposition adds a third axis the naive method cannot see: a site with normal `eta_true` but rising `P_aux` has a **cooling or auxiliary fault** that raw RTE would blame on the cells.

Only the bottom-right quadrant, and the elevated-`P_aux` cell, are inspection leads. The bottom-left will be large and none of it is technically fixable.

---

## FAULT SIGNATURE RULESET

Priority order, first match wins. Evaluate per site-month.

| # | Signature | Test | Recovery |
|---|---|---|---|
| 0 | HEALTHY | `eta_true ≥ 0.86`, `UTI ≥ 0.75`, `P_aux` within band | — |
| 1 | FULL_OUTAGE | Charge ≈ 0 and Discharge ≈ 0 while peer median EFC > 0.5 | 0.90 |
| 2 | AUGMENTATION | Step **increase** in `E_rated` between EIA-860 vintages, or EPC step up >15% | 0.00 — scheduled capex |
| 3 | PARTIAL_AVAILABILITY | Quantised fraction of trailing median, flat ≥2 months, step onset | 0.85 |
| 4 | THERMAL / AUX | `P_aux_summer − P_aux_shoulder` above the fleet p90 for its enclosure type, or `P_aux` trending up >20%/yr | 0.70 |
| 5 | CELL_DEGRADATION | `eta_true` declining ≥1.5 pts/yr with throughput unaffected | 0.25 |
| 6 | CAPACITY_FADE | EPC envelope declining >3%/yr against time-varying `E_rated`, ≥24 months | 0.25 |
| 7 | UNDER_DISPATCH | `eta_true ≥ 0.86` but `UTI < 0.60` | **0.00 — commercial** |
| 8 | HYBRID_ARTEFACT | Co-located flag set, or RTE > 1.0, or charge implausibly low | 0.00 — data issue |
| 9 | UNATTRIBUTED | Deficit present, nothing above fires | 0.30 |

---

## CRITICAL DATA ISSUE — hybrid contamination

Co-located solar-plus-storage sites may report storage charging from the host generator rather than the grid, or not report it at all. That produces RTE above 1.0 (physically impossible) or near-zero charge with substantial discharge.

Quarantine on any of:
- `RTE > 1.0` in any month
- `Co-Located Renewable Firming == Y` in EIA-860
- The same `Plant Id` also appears in `Page 1 Generation and Fuel Data` with prime mover `PV`

Report hybrids as a separate cohort. **Do not compute fleet efficiency statistics including them.**

---

## PART R — MONTHLY RELIABILITY LAYER

Same framework as the solar and gas builds. Unit of observation: the **plant-month**.

### R1 — Event ledger
```
D[i,y,s] = months carrying signature s        # duration
K[i,y,s] = maximal runs, 1-month gap tolerance # incidence
L_bar[s] = sum(D)/sum(K)
```
Track `exposure_months[i,y]` explicitly — this fleet is young and growing fast, so most sites have partial exposure. Never assume 12.

### R2 — Fault vs exposure vs state
| Ledger | Signatures |
|---|---|
| **Fault** | full outage, partial availability, thermal/aux, unattributed |
| **Exposure** | under-dispatch, hybrid artefact, augmentation |
| **State** | cell degradation, capacity fade |

### R3 — Hazard on two time axes
Fit Weibull hazards against **calendar age** and against **cumulative EFC** (throughput), and report which fits better. Battery warranties are throughput-based, so if cumulative EFC is the better time axis that is both a physical finding and a contractual one.

Expect infant mortality (`k < 1`) on commissioning-related outages — this fleet is young enough that first-year faults will dominate the ledger, and they occur while the EPC warranty is live.

### R4 — Rate model
```
log E[K] = log(exposure_months) + alpha_s + f_s(age) + g_s(cum_EFC)
           + beta_s' x_i + log u_i
```
`x_i`: duration band, chemistry, enclosure type, applications mix, BA, climate zone, vintage cohort, integrator where inferable.
Use **negative binomial** — expect heavy overdispersion on a fleet with this much heterogeneity.

### R5 — Credibility shrinkage — essential here
```
lambda_hat = Z * (K_own/E_own) + (1-Z) * lambda_pool,   Z = E_own/(E_own + tau_s)
```
Pool: same BA + duration band + vintage → same duration band + climate → whole fleet age-adjusted.

**This matters more for BESS than for any other technology** — median fleet age is roughly 2–3 years, so most assets have almost no own history and must borrow from the pool.

### R6 — Probability and expected loss
```
P[i,s](12mo) = 1 - (1 + lambda*12/phi)^(-phi)
EAL_MWh[i,s] = lambda*12 * L_bar[s] * delta_bar[s] * typical monthly discharge
```
Report in **MWh and efficiency points, not dollars** — see Guardrail 6.

### R7 — Backtest
Fit ≤ Y, predict Y+1. Calibration slope ≈ 1, AUC > 0.65, χ²/df ≈ 1 out of sample, must beat the fleet-mean baseline. Expect to fail the history requirement for most sites — say so rather than reporting a number.

---

## ACCEPTANCE GATES

| Check | Expected | Tolerance |
|---|---|---|
| Fleet median apparent RTE, 2025, standalone only | **0.851** | ±0.02 |
| Decomposed `eta_true`, fleet median | **0.889** | ±0.02 |
| Naive RTE on the same fitted sites | **0.844** | ±0.02 |
| Gap between the two | **~4.5 points** | ±1.5 |
| `P_aux` as % of nameplate, median | **0.21%** | p90 < ~1% |
| Sites with a usable aux decomposition | ~600 of ~960 | — |
| Total BESS discharge, 2025 | **26.5 TWh** | ±1 TWh |
| Total BESS discharge, 2019 | **430 GWh** | ±30 GWh |
| BESS nameplate, 2025 | ~40–43 GW | — |
| Median duration | **2.0 h** | — |
| Capacity join rate to EIA-860 | ≥98% | — |
| EIA published fleet RTE (external anchor) | ~82–85% | — |

Fleet RTE above 0.95 → hybrids included, or `Quantity` and `Grossgen` swapped.
`eta_true` below naive RTE → the regression is inverted; check that `x = h/Discharge`, not its reciprocal.

---

## GUARDRAILS

1. **Do not treat low throughput as underperformance.** It is the default state of a merchant battery in a quiet month. This is the biggest single way to get this wrong.
2. **Do not normalise by MW.** Use `Nameplate Energy Capacity (MWh)`.
3. **Do not compare RTE across duration bands.** C-rate moves it by 1–3 points or more.
4. **Do not assume static energy capacity.** Augmentation is contracted; build the time-varying series.
5. **Do not mix pumped storage or flywheels into the lithium cohort.**
6. **Do not quote a dollar figure without a revenue model.** Lost BESS MWh have no PPA price — the value of a cycle depends on the spread it captured. Report MWh and efficiency points, and say plainly that monetisation needs nodal price data you do not have.
7. **Do not report degradation on sites with <24 months.** Median fleet age is 2–3 years; `insufficient_history` is the correct and common answer.
8. **2025 is early release** and will be revised.

---

## DELIVERABLES

1. `bess_monthly.parquet` — plant × year × month: `Charge`, `Discharge`, `RTE`, `EFC`, `UTI`, `E_rated`, `Duration`, `T_amb`, `signature`, `quality_flags`.
2. `bess_efficiency_decomposition.csv` — one row per site: `eta_true`, `P_aux`, `P_aux_summer`, `P_aux_shoulder`, `P_aux_pct_nameplate`, rolling trends on each, fit `n` and R².
3. `bess_event_ledger.parquet` — plant × year × signature: duration, incidence, exposure months, MWh at stake.
4. `bess_site_summary.xlsx` — annual apparent RTE and decomposed efficiency, `P_aux`, EFC, UTI, fade slope, cumulative EFC and warranty position, availability months, dominant signature, applications, chemistry, enclosure, owner, customer group, SSI/prospect, hybrid flag.
5. `efficiency_decomposition.png` — scatter of `eta_true` against `P_aux`, coloured by duration band, with the fleet medians marked. This is the exhibit that explains the method.
6. `bess_leads.csv` — bottom-right quadrant plus elevated-`P_aux` sites, persistent ≥2 months, ranked by MWh at stake and by warranty headroom remaining.
7. `README.md` — method, gate results, hybrid quarantine list, explicit statement of what monthly data cannot determine.

---

## CONTEXT YOU SHOULD KNOW

**There is no published method for detecting grid-scale BESS faults from monthly public data.** The academic literature is almost entirely cell- and pack-level state-of-health estimation from high-frequency BMS telemetry, none of which applies here. The largest publicly available field dataset in the literature covers 21 *household* batteries. The auxiliary-load decomposition above is a genuine contribution — validate it aggressively and claim conservatively.

**The commercial space is occupied but not at this angle.** Modo Energy benchmarks BESS *revenue* across 13 markets; TWAICE and ACCURE sell *cell-level* analytics requiring owner data access. The gap is third-party efficiency and availability benchmarking computed entirely from public data, which can be run on a target's portfolio before any conversation with them.

**The fleet is young and growing explosively** — 430 GWh discharged in 2019 against 26.5 TWh in 2025, a 60-fold increase, capacity from under 1 GW to over 40 GW. Expect little degradation signal and a large cohort under two years old. The honest near-term output is efficiency decomposition and availability benchmarking, not degradation forecasting.

**Reported field efficiency varies widely by measurement boundary.** Cell-level LFP RTE is above 95%; system-level AC-to-AC at the point of interconnection is typically 85–90%; the EIA fleet average sits near 82%. Always state which boundary you are measuring. The decomposition lets you report both `eta_true` (closer to the conversion boundary) and apparent RTE (the grid-interface boundary) from the same data, which is exactly why it is worth doing.

---

## WORKING STYLE

Modular, re-runnable: `load_storage.py`, `load_860_allvintages.py`, `hybrid_filter.py`, `efficiency_decomp.py`, `peers.py`, `signatures.py`, `ledger.py`, `hazard.py`, `report.py`.

Print the acceptance gate table after every run and fail loudly on breach. Every threshold a named constant. Where a metric cannot be computed credibly from the available history, output `insufficient_history` rather than a number — on a fleet this young that will be common and it is the correct answer.
