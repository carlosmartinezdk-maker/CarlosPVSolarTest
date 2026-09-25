# Claude Code Prompt — Gas Fleet Heat Rate, Degradation & Reliability Analysis
**Version 2** — adds plant-level fuel cost, physical QC floors, fuel-security parameters, and a monthly reliability-engineering layer.

> Run: `claude "follow the spec in gas_analysis_prompt.md"`

---

## ROLE AND OBJECTIVE

You are building the gas-fired equivalent of a solar underperformance detection engine. The solar version measures generation against weather-corrected expectation. **For gas the equivalent metric is heat rate, not generation** — output is a dispatch decision, but *efficiency at a given output* is a physical property of the asset.

Objective: for every US gas plant, 2019–2025, compute **monthly** efficiency and reliability metrics; determine whether heat rate has degraded relative to its own history, comparable plants, and physical limits; quantify the fuel cost of that degradation using the plant's own delivered gas price; and classify it into recoverable and non-recoverable causes.

Everything is computed **month by month**, because the monthly series is what feeds the reliability layer in Part R.

---

## INPUTS

### Production and fuel
`/mnt/user-data/uploads/EIA923_Schedules_2_3_4_5_M_12_{2019..2024}_Final*.xlsx`
`/mnt/user-data/uploads/EIA923_Schedules_2_3_4_5_M_12_2025_Early_Release_30JUN2026.xlsx`

Sheet `Page 1 Generation and Fuel Data`. Header row 6, except the 2025 file where it is row 7 — detect by searching for `Plant Id` in the first 10 rows.

| Column set | Use |
|---|---|
| `Netgen {Month}` | Net generation, MWh |
| `Elec_MMBtu {Month}` | Fuel burned **for electricity only** — use for heat rate |
| `Total Fuel Consumption MMBtu` | Includes fuel for useful thermal output. **Only** for CHP thermal share |
| `Quantity` vs `Elec_Quantity` | Difference = fuel diverted to a thermal host |

### Fuel cost — ALREADY BUILT, use this file
`/mnt/user-data/outputs/eia923_page5_gas_fuel_cost_2019_2025.csv`

66,688 plant-months, 884 plants, merged from EIA-923 Page 5 across all seven years. Join on `plant_id` + `year` + `month`.

**Coverage: 94.1% of all gas generation and 91.6% of gas capacity** (Combined Cycle 97.6% of MWh, Gas Steam 85.6%, Gas Turbine 67.1%). 879 of 2,071 gas plants report receipts, but they are the large ones.

Key columns:
- `gas_cost_final` — **$/MMBtu, already converted from cents.** Use this.
- `cost_source` — `plant` (53.8%), `state` (37.4%), `national` (8.8%). Weight confidence accordingly; never quote a dollar figure sourced at `national` tier without saying so.
- `heat_content_MMBtu_per_Mcf` — median 1.03
- `firm_delivery_share`, `firm_supply_share`, `spot_share`, `tolling_share`, `n_suppliers`

Validation series (national average delivered gas, $/MMBtu): 2019 **3.09**, 2020 **2.66**, 2021 **5.36**, 2022 **7.30**, 2023 **3.89**, 2024 **3.05**, 2025 **4.07**. The 2020 COVID trough and the 2022 spike are both present at the right magnitude.

### Plant characteristics
Download EIA-860 **all vintages 2019–2025** — you need time-varying capacity, not a single snapshot:
```
https://www.eia.gov/electricity/data/eia860/xls/eia8602025.zip
https://www.eia.gov/electricity/data/eia860/archive/xls/eia860{2019..2024}.zip
```
From `3_1_Generator_Y{yyyy}.xlsx`, tabs `Operable` and `Retired and Canceled`, header row 2:
`Nameplate Capacity (MW)`, `Summer Capacity (MW)`, `Minimum Load (MW)`, `Technology`, `Prime Mover`, `Operating Year`, `Operating Month`, `Duct Burners`, `Can Bypass Heat Recovery Steam Generator?`, `Unit Code`.
Plus `2___Plant_Y{yyyy}.xlsx` (lat/lon, BA) and `4___Owner_Y{yyyy}.xlsx` (ownership — Schedule 4 covers only jointly-owned and non-operator-owned plants; fall back to the operating utility).

### Ambient temperature — required
Monthly mean dry-bulb per site from **NSRDB PSM3** by lat/lon (hourly → monthly mean, ideally also a generation-weighted monthly mean). Fallback: NOAA nClimGrid monthly by county. Do not proceed without it.

---

## TECHNOLOGY CLASSES

| Class | EIA-923 prime mover | EIA-860 Technology |
|---|---|---|
| Combined Cycle | CA, CT, CS | Natural Gas Fired Combined Cycle |
| Gas Turbine | GT | Natural Gas Fired Combustion Turbine |
| Gas Steam | ST | Natural Gas Steam Turbine |
| Gas Recip | IC | Natural Gas Internal Combustion Engine |

Gaseous fuel codes: `NG, OG, PG, BFG, LFG, OBG, SGC, SGP`.

**Combined cycle allocation — the most common way to get this wrong.** Fuel is reported almost entirely on `CT` rows while generation splits across `CT` and `CA`. Aggregate to plant × technology **before** computing heat rate. A heat rate on a `CA` row alone is meaningless.

---

## QUALITY CONTROL — physical efficiency floors (NEW)

An empirical run on this dataset produced simple-cycle heat rates as low as **4,201 Btu/kWh** at high load factor. That is thermodynamically impossible — it implies 81% efficiency. Those rows are misallocated fuel, usually a GT that is part of a combined cycle whose steam output is credited against combustion-turbine fuel alone.

Apply physical floors per class, not one blanket range:

| Class | Floor (Btu/kWh) | Ceiling | Rationale |
|---|---|---|---|
| Combined Cycle | **5,700** | 20,000 | Best H-class ≈ 5,700–6,200 HHV |
| Gas Turbine | **7,500** | 30,000 | Best aeroderivative ≈ 8,500; frame 9,500–11,000 |
| Gas Steam | **7,500** | 25,000 | |
| Gas Recip | **7,000** | 20,000 | |

Anything below the floor is a **data error, not a high-performing plant**. Quarantine into a `misallocated` bucket, report the count, and check whether the plant needs CA/CT re-aggregation. If more than ~5% of a class breaches the floor, the aggregation is wrong.

---

## MONTHLY METRICS — compute all per plant × technology × year × month

### M1 — Heat rate
```
HR[i,m] = Elec_MMBtu[i,m] * 1e6 / (Netgen[i,m] * 1000)      # Btu/kWh
```

### M2 — Load factor
```
LF[i,m] = Netgen[i,m] / (Nameplate_MW[i,year] * hours_in_month)
```

### M3 — Equivalent operating hours and starts proxy
```
EOH[i,m]          = Netgen[i,m] / Nameplate_MW[i,year]     # hours at full load
Cum_EOH[i,m]      = running sum since COD or since last detected wash
Starts_proxy[i,m] = derived from LF discontinuities and low-LF non-zero months
```
EOH matters because OEM compressor-wash intervals are specified in **fired hours (4,000–8,000)**, and because deferring an offline wash past the OEM interval adds **0.3–0.5% non-recoverable heat-rate degradation per 1,000 fired hours** that a wash can no longer reverse. A plant whose cumulative EOH since its last apparent wash exceeds 8,000 is a concrete, defensible lead.

### M4 — Load-factor reference curve (do not skip)

Measured on this dataset:

| Load factor | CC p10 | GT p10 |
|---|---|---|
| 0–5% | 7,417 | 10,239 |
| 20–30% | 5,956 | 4,825\* |
| 50–60% | 5,503 | 4,261\* |
| 80–100% | 6,344 | 4,201\* |

\* below the physical floor — misallocation, which is what the QC step catches.

**Envelope spread across the load range: CC 35%, GT 144%.** Rank on raw heat rate and you rank plants by how often they were dispatched, not by how well they run.

Fit, per class, a monotone reference from the **10th percentile of HR within each load-factor decile** (isotonic regression or monotone spline), *after* applying physical floors. Publish the curve — it explains the method in one picture.

### M5 — Temperature correction
```
HR_corr[i,m] = HR[i,m] / (1 + k_T * (T_amb[i,m] - 15))
```
Fit `k_T` per class by regressing log(HR) on ambient temperature **within load-factor bands**, so temperature is not confounded with dispatch. Expect ~0.1–0.3%/°C simple cycle, less for combined cycle. Wrong sign or magnitude → stop.

### M6 — Heat Rate Index (PI analogue)
```
HRI[i,m] = HR_ref_class(LF[i,m]) / HR_corr[i,m]
```
Inverted so **higher is better**, consistent with solar PI. `HRI = 0.92` means the plant burns 8% more fuel than a well-maintained comparable would, at the same output and ambient conditions.

### M7 — Peer Relative Index (PRI analogue)
Match on: same class; **unit size band** (`Nameplate_MW / n_units` — frame size drives efficiency); **vintage band** (COD ±5 years, the best public proxy for E/F/G/H frame class); same NERC region or within 500 km; load factor within ±0.10 that month.
```
PRI[i,m] = median(HR_corr of >=8 matched healthy peers, month m) / HR_corr[i,m]
```
**Peer health filter:** exclude peers whose own `HRI < 0.90` that month before taking the median.

### M8 — Own-best baseline
```
eta[i]       = 95th percentile of HRI[i,m] over the first 24 scoreable months
HRI_own[i,m] = HRI[i,m] / eta[i]
```
Cancels frame class, elevation, duct-firing configuration and every unknown design parameter. Most of this fleet has ≥24 months.

### M9 — Fuel quality and commercial exposure (from Page 5)
```
heat_content_drift[i,m] = heat_content[i,m] / median(heat_content[i, all months])
fuel_security[i,m]      = firm_delivery_share[i,m]
price_exposure[i,m]     = spot_share[i,m]
```
Heat content drifting off 1.03 MMBtu/Mcf propagates **directly** into computed heat rate — a metering or gas-quality issue masquerading as degradation. Check it before attributing anything.

`firm_delivery_share < 1.0` is interruptible gas exposure, present in 22,136 plant-months. It is a winter fuel-security risk and a genuine reliability parameter, not a performance one.

### M10 — CHP thermal share
```
thermal_share[i,m] = (Total_MMBtu[i,m] - Elec_MMBtu[i,m]) / Total_MMBtu[i,m]
```
Flag `thermal_share > 0.05` as cogeneration. Electric heat rate is valid but economics are not comparable — separate cohort.

---

## DEGRADATION DECOMPOSITION

Research anchors — use these to sanity-check the fitted components:

- **Compressor fouling accounts for 70–85% of all gas turbine efficiency deterioration over service life**, and it is recoverable.
- **A well-executed offline crank wash recovers 80–95% of fouling-induced losses.**
- Online and offline washing are complementary: online slows the fouling rate and extends the interval, offline resets the baseline.
- Industry trigger thresholds: heat rate rise >0.8% above corrected baseline, or compressor discharge pressure deviation >1.5% below rolling baseline.

| Component | Monthly signature | Recovery |
|---|---|---|
| **Compressor fouling** | HRI declines monotonically ≥3 months, then steps up ≥1.5%. Sawtooth. Stronger at coastal, arid and industrial sites. | 0.85 |
| **Hot gas path deterioration** | Slow monotone decline over 12–36 months, no reset, correlated with `Cum_EOH`. | 0.50 |
| **Non-recoverable** | Residual trend surviving washes and overhauls, typically 0.3–0.5%/yr. | 0.00 |
| **Cycling damage** | Decline correlated with `Starts_proxy` rather than `EOH`. | 0.00 — operating regime |
| **Duct-firing artefact** | HRI falls only at LF > 0.75 where `Duct Burners = Y`. | 0.00 — by design |
| **Fuel-quality artefact** | Deficit tracks `heat_content_drift`. | 0.00 — metering |
| **Cooling degradation** | Combined cycle only. HRI penalty concentrated in the warmest months, **surviving the ambient correction**, deepening year over year. See below. | 0.75 |
| **BoP intermittent** | Erratic non-seasonal HRI deficits, CV of monthly deficit ≥0.50, no step and no sawtooth, at a plant with elevated cycling or trip exposure. | 0.60 |

### COOLING_DEGRADATION — the one balance-of-plant fault with a thermodynamic footprint

Circulating-water pump degradation (impeller erosion, recirculation, fouled intake) and condenser fouling both reduce heat rejection, raising condenser backpressure and cutting steam turbine output. Roughly **2–3% steam turbine output per inHg of backpressure**, which on a combined cycle is about **1% of plant output** — detectable over 6–12 months but not in a single month.

Its signature is separable because the ambient correction in M5 already removes the *normal* seasonal penalty. What survives is the anomaly:

```
summer_residual[i,y] = mean(1 - HRI[i,m]) for m in Jun..Sep
shoulder_residual[i,y] = mean(1 - HRI[i,m]) for m in Mar..May, Oct..Nov
cooling_signal[i,y]  = summer_residual - shoulder_residual
cooling_trend[i]     = log-linear slope of cooling_signal over available years
```

Fire the signature when **all** of:
- `TECH == 'Combined Cycle'` (or Gas Steam with a condenser)
- `cooling_signal[i,y] >= 0.015` (1.5 points of extra summer heat rate penalty)
- `cooling_signal` exceeds the peer p75 for the same climate region and cooling type
- `cooling_trend > 0` across ≥3 years, or the signal is present in ≥2 consecutive years
- not already attributed to fouling (no sawtooth) or duct firing (check the LF band)

**Inspection scope this implies:** condenser performance test, circulating-water flow verification, and a vibration survey on the circ water pumps — the 1×/2×/broadband/VPF dictionary applies directly there.

**Limit to state plainly:** this detects the *system-level consequence*, not the pump. Total failure of even the largest auxiliary pump on a 500 MW plant is roughly 1.2% of output, which sits at the 12-month detection floor (measured month-over-month heat rate noise on stable baseload CC is σ = 2.25%, so the 2σ floor is 4.5% for a single month and 1.30% sustained over 12). A developing bearing fault is orders of magnitude below that. Never imply the model sees pumps.
| **Misallocation** | HR below physical floor. | excluded entirely |

Since fouling is 70–85% of recoverable loss, **if your decomposition attributes less than about half of recoverable degradation to fouling, the sawtooth detector is too strict.** Loosen and re-check.

---

## ECONOMICS

```
Excess_MMBtu[i,m] = Netgen[i,m] * 1000 * (HR_corr[i,m] - HR_target[i,m]) / 1e6
Waste_USD[i,m]    = Excess_MMBtu[i,m] * gas_cost_final[i,m]
```
`HR_target` = peer 75th percentile of HRI at the same load factor — 25% of comparable assets already achieve it, so it is demonstrably attainable rather than theoretical.

Apply the recovery fraction by component, then payback against an inspection/remediation cost table kept as an **editable input with placeholder values, clearly labelled unvalidated**.

Scale cross-check: a 5% compressor efficiency drop on a 100 MW turbine is roughly **$1.2M/yr** of extra fuel. If your per-plant figures sit an order of magnitude away for comparable degradation, investigate.

---

## PART R — MONTHLY RELIABILITY LAYER (why everything is monthly)

Unit of observation: the **plant-month**.

### R1 — Event ledger: duration vs incidence
```
D[i,y,s] = months in year y carrying signature s                   # duration -> MMBtu and $
K[i,y,s] = count of maximal runs of s, 1-month gap tolerance       # incidence -> probability
L_bar[s] = sum(D) / sum(K)                                         # mean episode duration
```
Conflating these corrupts every rate model: a five-month fouling episode is **one event lasting five months**.

Track `exposure_months[i,y]` explicitly — never assume 12. Plants enter at COD, exit at retirement, and months drop out through QC.

### R2 — Separate faults from exposures
| Ledger | Signatures | Modelled as |
|---|---|---|
| **Fault** | fouling, HGP, cycling damage | recurrent events → hazard model |
| **Exposure** | duct firing, fuel-quality artefact, interruptible-gas curtailment | site characteristics |
| **State** | non-recoverable degradation | continuous trend |

### R3 — Hazard shape, on two time axes
Fit a Weibull hazard per signature against **both** calendar age and cumulative EOH, and report which fits better:
```
h_s(t) = (k_s / eta_s) * (t / eta_s)^(k_s - 1)
```
`k < 1` infant mortality (commissioning quality → warranty claim); `k ≈ 1` random; `k > 1` wear-out (schedule preventative work).

Expect fouling to be `k ≈ 1` against calendar age but strongly `k > 1` against **EOH since last wash**. That difference is the entire argument for condition-based rather than calendar-based washing, and it is the strongest commercial finding available from this data.

### R4 — Rate model
```
log E[K[i,y,s]] = log(exposure_months[i,y]) + alpha_s + f_s(age) + g_s(cum_EOH)
                  + beta_s' x_i + log u_i
```
`x_i`: class, unit size, vintage, climate region (coastal / arid / industrial — fouling is environment-driven), BA, firm-delivery share, duct burners, CHP flag.
`u_i`: site frailty random effect.

**Auxiliary-wear covariates — add these when CEMS is available.** Starts and trips are what destroy balance-of-plant equipment: lube oil pumps cycle on every start, feedwater and condensate pumps thermal-cycle, and every trip is a hard transient through the whole water/steam path. They are exposure variables for BoP failure, and they are only visible hourly.

```
starts_per_MW_yr[i]   = CEMS start count / nameplate MW          # cycling intensity
trip_rate[i]          = abrupt drops from >40% load to zero, per 1,000 operating hours
cold_start_share[i]   = starts after >48 h offline / total starts  # harshest on BoP
ramp_p95[i]           = 95th percentile hourly |ΔMW| / nameplate MW
cum_starts[i]         = running total since COD
```

Include `log(1 + starts_per_MW_yr)`, `trip_rate` and `cold_start_share` in `x_i` for the BoP and cooling signatures specifically. Expect `k > 1` (wear-out) against cumulative starts even where calendar age shows nothing — a plant converted from baseload to cycling duty accumulates BoP wear on a completely different clock from its nameplate age, and that divergence is the finding.

Without CEMS, use weak monthly proxies and label them as such: `CV of monthly load factor` for cycling duty, and months with `0 < LF < 0.15` as a crude start indicator. They are far worse than the real thing — flag any BoP conclusion built on them as low confidence.

**Use negative binomial, not Poisson.** On the solar fleet the variance/mean ratio was 3.24; expect similar or worse here. Poisson would report intervals ~1.8× too narrow.

### R5 — Credibility shrinkage
```
lambda_hat = Z * (K_own / E_own) + (1 - Z) * lambda_pool,   Z = E_own / (E_own + tau_s)
```
Pool hierarchy: same class + size + vintage nearby → same class + climate region → same class → whole fleet age-adjusted.

### R6 — Probability and expected annual loss
```
P[i,s](12mo) = 1 - (1 + lambda*12/phi)^(-phi)
EAL[i,s]     = lambda*12 * L_bar[s] * delta_bar[s] * MMBtu_per_month[i] * gas_cost_final[i]
```
Report components, not just a total: *"68% chance of a fouling episode in 12 months, typically 4 months long, typically 2.1% heat rate, worth $340k at your gas price"* is actionable. A single risk score is not.

### R7 — Preventative decision rule
```
Act if  EAL[i,s] * recovery_s * horizon > preventative_cost[i,s]
```
Preventative work is rational **only for wear-out signatures** (`k > 1`). For infant-mortality signatures the answer is commissioning QA and warranty enforcement — replacing the part resets you to the high-risk end of the curve.

### R8 — Backtest (mandatory before any predictive claim)
Fit on years ≤ Y, predict Y+1. Report calibration (predicted vs observed by decile, slope ≈ 1), discrimination (AUC > 0.65), Pearson χ²/df ≈ 1 out of sample, and whether it beats "predict the fleet mean". Calibration matters more than discrimination — a model that ranks correctly but says 40% when the truth is 12% destroys credibility the first time someone tracks it.

---

## PART B — BALANCE-OF-PLANT RISK INDEX AND TARGETING

The purpose of this part is commercial: produce a **filterable prospect list, by site and by customer**, of assets whose profile matches balance-of-plant degradation — so a vibration survey and condenser work can be sold into the right accounts.

Be clear about what this is. It is a **propensity score, not a diagnosis.** It says "this plant has the profile of a plant with BoP problems." It never says which pump.

### B1 — Components

Score each component 0–100 as a percentile against the peer group (same class, size band, climate region). Two are **evidence**; the rest are **exposure**.

| | Component | Source | Type |
|---|---|---|---|
| C1 | `cooling_signal` strength and trend | monthly HRI residual | **evidence** |
| C2 | `UNATTRIBUTED` + `BOP_INTERMITTENT` share of the plant's total HRI deficit | signature ledger | **evidence** |
| C3 | `starts_per_MW_yr` and `cum_starts` | CEMS (proxy: LF variance) | exposure |
| C4 | `trip_rate` vs peers | CEMS | exposure |
| C5 | `ramp_p95` | CEMS | exposure |
| C6 | BoP age — years since **original** COD, not the latest uprate | EIA-860 | exposure |
| C7 | Interruptible gas exposure `1 - firm_delivery_share` | Page 5 | exposure |

C6 matters more than it looks. Hot gas path parts get replaced on a maintenance cycle; **circulating water pumps, condensate pumps and condensers are frequently original equipment for the life of the plant.** A 2003 combined cycle that has had two HGP overhauls still has 20-year-old circ water pumps.

### B2 — The index

```
BPRI[i] = 0.30*C1 + 0.25*C2 + 0.15*C3 + 0.10*C4 + 0.05*C5 + 0.10*C6 + 0.05*C7
```
Evidence carries 55% of the weight; exposure 45%. Keep every weight a named constant — they are judgement, not measurement, and they must be tunable when ground truth arrives.

Where CEMS is unavailable, renormalise the remaining weights and set `bpri_confidence = 'low'`. Never blend a CEMS-backed score and a proxy-backed score in the same ranking without carrying that flag.

### B3 — Conviction tiers

| Tier | Test | Sales motion |
|---|---|---|
| **CONFIRMED** | C1 ≥ p75 **and** C2 ≥ p75, persistent ≥2 years | Condenser performance test + circ water pump vibration survey. Lead with the measured summer penalty. |
| **LIKELY** | C1 **or** C2 ≥ p75, with exposure composite ≥ p60 | Diagnostic visit, scope TBD. |
| **EXPOSED** | Exposure composite ≥ p80, no current evidence | **Preventative sale** — nothing is wrong yet. Sell a baseline survey and a monitoring plan, not a repair. |
| **LOW** | everything else | No action. |

The EXPOSED tier is the one most likely to be undervalued. A plant with heavy cycling, high trip rate and 20-year-old original BoP that is *currently performing fine* is the best preventative-maintenance prospect in the fleet, and no competitor screening on current performance will find it.

### B4 — Customer roll-up (this is the targeting output)

For every customer group, over their gas fleet:

```
sites_total, sites_confirmed, sites_likely, sites_exposed
mw_at_risk        = capacity in CONFIRMED + LIKELY
share_at_risk     = mw_at_risk / total gas MW            <- the key number
bpri_weighted     = capacity-weighted mean BPRI
recoverable_usd   = sum of cooling + BoP recoverable $ across their fleet
worst_site        = highest BPRI site name
is_ssi_customer   = from the customer mapping
```

**`share_at_risk` is the metric that changes the conversation.** One flagged plant is a site-level maintenance issue. Eight of a customer's ten plants flagged is a systemic O&M problem — a different contractor, a different spares policy, a portfolio-level conversation with a different buyer and a much larger contract. Rank customers on `share_at_risk` with a minimum fleet size of 3 sites so a single-asset owner at 100% does not top the list.

Produce both orderings and say which is which:
- by `recoverable_usd` — the biggest prize
- by `share_at_risk` — the most systemic, and the easiest to open a conversation with

Split every output by `is_ssi_customer` so existing accounts (cross-sell, warm intro) are separated from prospects (cold outreach).

### B5 — Outputs

1. `bop_site_targets.csv` — one row per plant: `plant_id`, `plant_name`, `customer`, `is_ssi_customer`, `state`, `ba`, `tech`, `mw`, `original_cod`, `bop_age`, C1–C7 scores, `BPRI`, `bpri_confidence`, `tier`, `cooling_signal`, `cooling_trend`, `summer_penalty_pct`, `starts_per_MW_yr`, `trip_rate`, `recoverable_usd`, `dominant_signature`, `suggested_scope`.
2. `bop_customer_targets.csv` — the B4 roll-up, both orderings, SSI split.
3. `bop_evidence_pack/{plant_id}.md` — for the top 25 CONFIRMED sites, a one-page brief: the monthly HRI series with summer months highlighted, the year-over-year cooling signal, peer comparison, exposure profile, and the specific inspection scope implied. This is the artefact that goes into a first meeting.

### B6 — Honesty requirements for anything customer-facing

Every brief must state:
- The model detects a **system-level thermodynamic consequence**, not a component fault.
- The detection floor: 4.5% heat rate change in a single month, 1.30% sustained over 12 (measured, σ = 2.25% month-over-month on stable baseload CC).
- That confirming the cause requires on-site work — condenser performance test and pump vibration survey.
- Where `bpri_confidence = 'low'` (no CEMS), that the cycling and trip exposure are proxies.

Do not produce a brief that implies pump-level diagnosis from public data. The prospect's engineer will know it is impossible, and the credibility cost exceeds the value of the meeting.

---

## ACCEPTANCE GATES

| Check | Expected | Tolerance |
|---|---|---|
| CC median heat rate, 2025 | **7,307 Btu/kWh** | ±200 |
| GT median heat rate, 2025 | **11,353 Btu/kWh** | ±400 |
| CC capacity, 2025 | ~333 GW | ±5 GW |
| GT capacity, 2025 | ~160 GW | ±5 GW |
| Capacity join rate, CC and GT | ≥95% | — |
| Plant-months below physical floor, after re-aggregation | <5% per class | — |
| National delivered gas, 2022 | **$7.30/MMBtu** | ±0.20 |
| National delivered gas, 2020 | **$2.66/MMBtu** | ±0.15 |
| Fitted `k_T` sign | positive | — |
| Non-recoverable degradation, fleet median | 0.3–0.6%/yr | — |
| Fouling share of recoverable degradation | 0.70–0.85 | — |
| Variance/mean of fault counts | >2 → negative binomial | — |
| Month-over-month HR noise, stable baseload CC | **σ = 2.25%** | ±0.4 |
| COOLING_DEGRADATION prevalence, CC fleet | 5–20% of CC plants | sanity |
| CONFIRMED tier share of gas fleet | <10% | if higher, C1/C2 thresholds are too loose |

CC heat rate near 3,000, or GT below 7,500 → CA/CT aggregation is wrong. Fix that first.

**Gas Steam matches EIA-860 at only ~52%** — EIA-923 reports any steam turbine burning gas while EIA-860 files coal and biomass co-firing plants under their primary fuel. Report separately, flag as indicative.

---

## GUARDRAILS

1. **Never rank on raw heat rate.** Load-factor spread is 35% (CC) to 144% (GT).
2. **Never compute heat rate on a `CA` row alone.**
3. **Do not proceed without ambient temperature.**
4. **Do not use `Total Fuel Consumption MMBtu` for heat rate** — it includes thermal-host fuel at CHP sites.
5. **`FUEL_COST` in raw EIA-923 is CENTS per MMBtu.** The merged file has already converted it — do not divide twice.
6. **Page 5 receipts are deliveries, not burn.** Price series only, never a consumption series.
7. **Do not present dollars as a quote** until recovery fractions and costs are vendor-validated.
8. **2025 is early release** and will be revised.
9. **A heat rate below the physical floor is a data error, not good performance.**
10. **Never imply the model sees individual pumps or bearings.** Total failure of the largest auxiliary pump on a 500 MW plant is ~1.2% of output, at the 12-month detection floor. The model detects system-level consequences — condenser backpressure, cooling degradation — and nothing finer. Vibration diagnosis requires on-site instrumentation.

---

## DELIVERABLES

1. `gas_monthly.parquet` — plant × tech × year × month: `HR`, `HR_corr`, `LF`, `EOH`, `cum_EOH`, `T_amb`, `HRI`, `PRI`, `HRI_own`, `signature`, `Excess_MMBtu`, `Waste_USD`, `gas_cost_final`, `cost_source`, `heat_content_drift`, `firm_delivery_share`, `thermal_share`, `cooling_signal`, `qc_flags`.
2. `gas_event_ledger.parquet` — plant × year × signature: duration, incidence, exposure months, MMBtu and USD lost, max severity.
3. `gas_plant_summary.xlsx` — annual HRI/PRI, degradation slope, dominant component, EOH since last apparent wash, recoverable USD, payback, EAL and 12-month probability per signature, conviction tier, owner, customer group, SSI/prospect.
4. `heat_rate_curves.png` — HR vs load factor by class, fitted envelope, physical floors marked.
5. `hazard_curves.png` — Weibull hazards by signature, against both calendar age and cumulative EOH.
6. `gas_leads.csv` — both indices flag, ≥2 consecutive months, ranked by recoverable USD, with conviction tier and wash-interval status.
7. `bop_site_targets.csv`, `bop_customer_targets.csv`, `bop_evidence_pack/` — Part B outputs.
8. `README.md` — method, gate results, assumptions register.

---

## OPTIONAL UPLIFT — EPA CEMS

Hourly gross load, heat input and operating time at unit level, >25 MW, back to 1995, free at `https://campd.epa.gov/data/bulk-data-files`.

Gives: a true per-unit heat-rate curve from thousands of hourly points instead of a per-class statistical one; **real start counts and hot/warm/cold cycles**, which drive LTSA maintenance intervals; exact rather than statistical part-load separation; fouling detection within weeks rather than months.

**Extract these specifically for the balance-of-plant layer (Part B):**
```
start        = transition from GLOAD == 0 for >=1 h to GLOAD > 5% of max, sustained >=2 h
trip         = drop from GLOAD > 40% of max to 0 within <=2 h, with no ramp-down
cold_start   = start after >48 h offline;  warm 8-48 h;  hot <8 h
ramp_rate    = hourly delta GLOAD / nameplate MW
op_hours     = hours with GLOAD > 0
```
`starts_per_MW_yr`, `trip_rate` per 1,000 operating hours, `cold_start_share` and `ramp_p95` are the auxiliary-wear covariates in R4 and components C3–C5 of the BoP index. **They are the single largest uplift to the BoP targeting layer** — without them C3–C5 fall back to weak monthly proxies and every BoP conclusion carries `bpri_confidence = 'low'`.

Caveat: the CAMD-to-EIA crosswalk is imperfect — EPA "units" are emissions points, EIA "generators" are electrical. Use the published crosswalk and validate annual heat input against EIA-923 within ±5%.

**Monthly is triage; hourly CEMS is diagnosis.**

---

## WORKING STYLE

Modular, re-runnable: `load_923.py`, `load_860_allvintages.py`, `fuel_cost.py`, `weather.py`, `qc_floors.py`, `heat_rate.py`, `peers.py`, `components.py`, `ledger.py`, `hazard.py`, `economics.py`, `report.py`.

Print the acceptance gate table after every run and fail loudly on breach. Every threshold a named constant at the top of its module. When a result looks too good, assume an aggregation bug and check the gates before reporting it.

---

## ADD-ON — RESULTS INFOGRAPHIC

After the deliverables above exist, build the interactive results infographic specified in
**`infographic_addon.md`** (shared with the other technology prompt).

It is a single self-contained HTML file in the same editorial design system as the existing
fleet infographic (`us_fleet_infographic.html`, which is the working reference implementation —
read its CSS and render functions rather than inventing a new design language).

Key points for this technology, detailed in the add-on:
- Map dots sized by capacity, **coloured by HRI** on the diverging performance scale
- Stacked chart of **recoverable $ by fault signature**, with non-recoverable and by-design
  components stacked in browns and grey above the recoverable share
- Site table carrying HRI, PRI, heat rate, load factor, EOH since last wash, dominant
  signature, recoverable $/yr and payback
- Footer must state that recovery fractions and remediation costs are unvalidated placeholders,
  and that fuel cost is plant-tier for only 53.8% of plant-months

Do not start it until the acceptance gates in this spec pass. An infographic built on an
unvalidated pipeline just makes a wrong number look authoritative.
