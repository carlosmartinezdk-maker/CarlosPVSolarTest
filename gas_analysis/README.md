# Gas fleet heat rate, degradation and reliability (EIA-923 monthly, 2019–2025)

This builds the spec in `gas_analysis_prompt.md` (v2). It covers every US gas plant × technology class, month by month. The heat rate is corrected for load factor and temperature and benchmarked three ways: against a physical reference envelope, against matched peers and against the plant's own best. The deficit is split into recoverable and non-recoverable components and priced at the plant's own delivered gas cost. On top sits a monthly reliability layer: event ledger, Weibull hazards, negative-binomial rates, credibility shrinkage and a backtest.

**Monthly is triage, not diagnosis.** Every dollar figure here is indicative. Recovery fractions and remediation costs are unvalidated placeholders (Guardrail 7).

## Run

```bash
pip install pandas numpy scipy scikit-learn statsmodels openpyxl pyarrow matplotlib
# raw data: EIA-923 2019-2025, EIA-860 2019-2025, NOAA nClimGrid county files, Natural Earth land-50m
#   -> data/raw (zips + climdiv files) and data/x/<zipname>/ (extracted). See "Data sources" below.
python run.py --force      # ~1 min after the first load; prints the gate table and exits 1 on any FAIL
```

Run `python load_923.py` and `python load_860_allvintages.py` once first. They build the parquet caches in `data/cache`.

Modules follow the spec's layout: `load_923.py`, `load_860_allvintages.py`, `fuel_cost.py`, `weather.py`, `qc_floors.py`, `heat_rate.py`, `temperature.py`, `reference.py`, `peers.py`, `components.py`, `economics.py`, `ledger.py`, `hazard.py`, `reliability.py`, `climate.py`, `leads.py`, `report.py`, with `pipeline.py` and `run.py` driving them. Every threshold is a named constant at the top of its module.

## Deliverables (`outputs/`)

| File | Content |
|---|---|
| `gas_monthly.parquet` | 251,388 plant × class × month rows (3,002 plants; 117,866 scoreable). HR, HR_corr, HR_ref, HR_target, LF, EOH, cum_EOH, EOH_since_wash, starts proxy, T_amb, HRI, PRI (+peer tier/count), HRI_own, signature, wash flag, Excess_MMBtu, Waste_USD, Recoverable_USD, gas cost and source, heat-content drift, firm/spot shares, thermal share, qc_flags |
| `gas_event_ledger.parquet` | plant × class × year × signature: D (months), K (episodes), exposure months, MMBtu/USD lost, recoverable USD, max severity, ledger type, L̄ |
| `gas_episodes.parquet` | one row per episode (maximal run, 1-month gap tolerance) |
| `gas_plant_summary.xlsx` | plant summary (annual HRI/PRI, slopes, dominant component, EOH since wash, recoverable USD, payback, λ/P12/EAL/decision per fault signature, conviction tier, owner) plus sheets for leads, gates, k_T, reference curves, hazards, rate models, backtest, risk, remediation costs and the assumptions register |
| `heat_rate_curves.png` | HR vs LF by class, p10 per bin, monotone envelope, physical floors, quarantined points |
| `hazard_curves.png` | Weibull hazards by signature on calendar age and cumulative EOH, plus fouling re-onset since wash |
| `gas_leads.csv` | 491 plant × class leads (15 tier A, 22 tier B), ranked by recoverable USD over the last 24 months, with wash-interval status |
| `gate_results.csv`, `run_log.txt` | gate table and the full console output of the last run |

## Acceptance gates (last run)

| Check | Expected | Got | Status | Note |
|---|---|---|---|---|
| CC median heat rate 2025 (plant-month, pre-floor QC — spec definition) | 7,307 ±200 | 7303 | **PASS** | post-QC scoreable median = 7,368 |
| GT median heat rate 2025 (plant-month, pre-floor QC — spec definition) | 11,353 ±400 | 11353 | **PASS** | post-QC scoreable median = 11,912 |
| CC capacity 2025 (GW, EIA-860 nameplate) | ~333 ±5 | 328.3 | **PASS** |  |
| GT capacity 2025 (GW, EIA-860 nameplate) | ~160 ±5 | 161.7 | **PASS** |  |
| Capacity join rate CC (plant-months) | >=0.95 | 0.999 | **PASS** | same-vintage join 0.997 |
| Capacity join rate GT (plant-months) | >=0.95 | 0.997 | **PASS** | same-vintage join 0.991 |
| Gas Steam join rate (indicative) | ~0.52 (spec) | 0.552 | **PASS** | gas-fuel ST rows only; coal co-firing units filed under coal in 860 are excluded upstream |
| Plant-months below floor after re-aggregation, CC (non-CHP) | <0.05 | 0.0191 | **PASS** | CHP cohort 0.352 (EIA CHP fuel allocation, reported separately) |
| Plant-months below floor after re-aggregation, GT (non-CHP) | <0.05 | 0.0136 | **PASS** | CHP cohort 0.651 (EIA CHP fuel allocation, reported separately) |
| Plant-months below floor after re-aggregation, ST (non-CHP) | <0.05 | 0.0038 | **PASS** | CHP cohort 0.704 (EIA CHP fuel allocation, reported separately) |
| Plant-months below floor after re-aggregation, IC (non-CHP) | <0.05 | 0.0133 | **PASS** | CHP cohort 0.419 (EIA CHP fuel allocation, reported separately) |
| National delivered gas 2022 ($/MMBtu) | 7.30 ±0.2 | 7.32 | **PASS** |  |
| National delivered gas 2020 ($/MMBtu) | 2.66 ±0.15 | 2.66 | **PASS** |  |
| k_T sign, CC | positive | 0.091 %/degC | **PASS** | hinge form: applied above 15 degC |
| k_T magnitude, CC | 0.1-0.3 %/degC simple cycle; less for CC | 0.091 %/degC | **PASS** |  |
| k_T sign, GT | positive | 0.070 %/degC | **PASS** | hinge form: applied above 15 degC |
| k_T magnitude, GT | 0.1-0.3 %/degC simple cycle; less for CC | 0.070 %/degC | **WARN** |  |
| k_T sign, IC | positive | 0.057 %/degC | **PASS** | hinge form: applied above 15 degC |
| k_T magnitude, IC | 0.1-0.3 %/degC simple cycle; less for CC | 0.057 %/degC | **PASS** |  |
| k_T sign, ST | positive | 0.119 %/degC | **PASS** | hinge form: applied above 15 degC |
| k_T magnitude, ST | 0.1-0.3 %/degC simple cycle; less for CC | 0.119 %/degC | **PASS** |  |
| Non-recoverable degradation, fleet median (%/yr) | 0.3-0.6 | 0.057 | **FAIL** | annual-p90 envelope of HRI_own; raw annual CC heat-rate trend is also ~0 |
| Fouling share of recoverable degradation | 0.70-0.85 | 0.851 | **FAIL** |  |
| Variance/mean of fault counts, FOULING (plant-years, exposure>=6) | >2 -> negative binomial | 0.79 | **WARN** | NB alpha=0.000; model used: poisson (alpha~0) |
| Variance/mean of fault counts, HGP (plant-years, exposure>=6) | >2 -> negative binomial | 1.31 | **WARN** | NB alpha=2.426; model used: negative binomial |
| Variance/mean of fault counts, CYCLING (plant-years, exposure>=6) | >2 -> negative binomial | 1.33 | **WARN** | NB alpha=6.723; model used: negative binomial |
| Backtest FOULING (fit<=Y, predict Y+1, 2022-2025) | AUC>0.65, slope~1, chi2/df~1, beats baseline | AUC 0.68, slope 1.21, chi2/df 0.84, beats mean True | **WARN** |  |
| Backtest HGP (fit<=Y, predict Y+1, 2022-2025) | AUC>0.65, slope~1, chi2/df~1, beats baseline | AUC 0.78, slope 0.95, chi2/df 4.02, beats mean True | **WARN** |  |
| Backtest CYCLING (fit<=Y, predict Y+1, 2022-2025) | AUC>0.65, slope~1, chi2/df~1, beats baseline | AUC 0.76, slope 1.05, chi2/df 5.43, beats mean True | **WARN** |  |
| Scale cross-check: fouling waste scaled to 100 MW & 5% ($/yr) | ~1.2M (within an order of magnitude) | 304,494 | **PASS** | spec example assumes ~60% CF; fouling plants here run lower |

**Summary: 21 PASS, 7 WARN, 2 FAIL.** `run.py` exits 1 because of the two FAILs, and both are reported as findings rather than tuned away.

- **Non-recoverable degradation, 0.06%/yr against 0.3–0.6%/yr.** This is not an artefact of the envelope method. The raw annual heat-rate log-slope of CC units with monthly data is also about 0.00%/yr (GT 0.08, IC 0.04). Over 2019–2025 the fleet's net heat-rate trend is flat. Major inspections, upgrades and repowerings that reset the curve inside a 7-year window are the likely reason. Measuring the 0.3–0.5%/yr residual would need a longer history or CEMS unit-level data that separates overhauls.
- **Fouling share, 0.851 against 0.70–0.85.** This is marginal, just over the top of the band. The spec only warns if the share falls below ~0.5 (detector too strict). The HGP detector requires no wash inside its 18-month window, and with about 3,300 detected washes that is a strict condition, so HGP is probably under-counted slightly.

### Other results that differ from the spec's expectations

1. **The spec's median heat rates are pre-QC numbers.** The gate values (CC 7,307, GT 11,353) are reproduced exactly by the plant-month median *before* the physical floors are applied. After quarantining sub-floor months, the scoreable medians are CC 7,368 and GT 11,912. Both are reported.
2. **The floor breaches are CHP allocation, not CA/CT.** Before the CHP split, 20% of GT and 38% of ST plant-months breached the floor. 86–99% of breaching rows are CHP plants, where EIA books part of the fuel to useful thermal output and the electric heat rate falls to about 4,000–5,000. In the non-CHP fleet the breach rate is 0.4–1.9% in every class. CHP is a separate cohort (M10), and its breach rates are shown in the gate notes.
3. **A new QC rule: CA generation missing.** One example is Bethlehem Energy Center (NY), where the CA row reports 0 MWh from 2023 while CT fuel continues, so the "heat rate" jumps from 7,000 to 10,500. Across the fleet, 758 CC months at 133 plants have steam share below 20% of their own median. These are quarantined (`misalloc:ca_generation_missing`). Before this rule the plant was the #1 lead at $34M.
4. **Annual respondents.** 61% of GT and 90% of IC plant-months (40% and 75% of MWh) come from EIA-923 annual respondents. Their monthly values are EIA allocations of an annual total, with a median within-year HR CV of exactly 0. Monthly components cannot be resolved for them, so their deficit months are `ANNUAL_ONLY` and they are left out of sawtooth detection. Otherwise every year boundary would look like a wash.
5. **Temperature response is a hinge.** Fitted within plant × LF band, the monthly response is about 0 below 15 °C and 0.07–0.17%/°C above. A symmetric linear k_T fits about 0.03–0.04%/°C and would "correct" winter months the wrong way. The hinge form `HR/(1+k_T·max(T−15,0))` is used. GT k_T of 0.07%/°C is positive but below the spec's 0.1–0.3%. Monthly-mean temperature, which includes nights, attenuates the effect, and inlet cooling on peakers flattens it. Using daily-maximum temperature did not change this.
6. **Fouling hazard.** Fouling re-onset after a detected wash is wear-out against **calendar months** (k = 1.12 [1.09, 1.15]). Against **EOH since wash** it is k = 0.79 [0.77, 0.81], and calendar time fits better by AIC (7,068 vs 8,934, with the EOH likelihood converted to a calendar density). This is the opposite of the spec's expectation (k ≈ 1 calendar, k > 1 EOH). One caveat: detection needs ≥3 months of decline, which imposes a minimum gap on the calendar axis and pushes its k up. The data therefore don't support the condition-based-washing argument as stated, but they don't refute it either. Hourly CEMS would settle it. HGP fits best on cumulative EOH with k ≈ 1 (random). Cycling fits best on calendar age with k = 1.17.
7. **Dispersion.** Plant-year fault counts are *not* overdispersed for fouling (variance/mean 0.79; NB α → 0, so a Poisson model is used). The sawtooth definition physically caps episodes per year. HGP (α = 2.4, LR test 100) and cycling (α = 6.7, LR 66) are overdispersed and use negative binomial.
8. **Backtest (fit ≤ Y, predict Y+1, 2022–2025, 3,746 plant-years).** Fouling: AUC 0.68, calibration slope 1.21, χ²/df 0.84. HGP: AUC 0.78, slope 0.95, χ²/df 4.0. Cycling: AUC 0.76, slope 1.05, χ²/df 5.4. All three beat the fleet-mean baseline on Brier score. Discrimination and calibration are acceptable. The χ²/df for the rare signatures is inflated by events at plants predicted near the rate floor. These are WARN, not PASS.

## Method (short)

- **Aggregation.** Gas-fuel rows (NG, OG, PG, BFG, LFG, OBG, SGC, SGP, plus CA waste-heat rows) are summed to plant × class × month *before* the heat rate is computed (CC = CA + CT + CS). Plant-years where most GT months breach the floor while the plant has CA generation are merged into CC.
- **QC.** Physical floors and ceilings are applied per class, and the CHP cohort is split out (thermal share > 5% or CHP flag). CA-missing months are quarantined. Scoring uses LF 0.02–1.10 only.
- **Temperature.** NOAA nClimGrid county monthly mean is used, since NSRDB needs an API key. 99.5% of counties matched and the rest borrow the nearest county within 150 km. Plant-month coverage is 99.7%.
- **Reference (M4).** The p10 of HR_corr in each LF bin on the non-CHP fleet, made monotone with isotonic regression. After QC the envelope spread is CC 16%, GT 5%, ST 8%, IC 6%. The spec's 35%/144% included the misallocated rows.
- **HRI = HR_ref(LF)/HR_corr.** PRI is the median HR_corr of ≥8 healthy matched peers (same class, unit-size band, COD ±5 y, same NERC or ≤500 km, LF ±0.10, peer HRI ≥ 0.90) divided by own HR_corr. When the strict match finds fewer than 8 peers, region is dropped (tier 2) and then vintage is widened to ±10 y (tier 3). Coverage of scoreable non-CHP months: CC 68%, GT 64%, IC 34%, ST 6%.
- **HRI_own = HRI / p95(HRI over first 24 scoreable months).** A month is in deficit when HRI_own < 0.95.
- **Components** (first match wins): MISALLOCATED > FUEL_QUALITY (heat content ±2%) > DUCT_FIRING (duct burners and HRI_own drops only above LF 0.75) > FOULING (sawtooth: ≥2 of 3 declining months totalling ≥0.8%, then a persistent ≥1.5% step up) > CYCLING > HGP (18-month slope ≤ −1.5%/yr tracking cum EOH, no wash) > NONRECOVERABLE (annual-p90 envelope slope ≤ −0.3%/yr) > UNATTRIBUTED.
- **Economics.** Excess is measured against HR_target = HR_ref / p75 HRI of the same class, LF bin and year. **Recoverable * = recovery × min(excess vs target, excess vs own best) × plant gas price. Maintenance can only restore a unit to its own best, not to a better peer's design. Payback uses `inputs/remediation_costs.csv` (UNVALIDATED placeholders). 2025 totals: $2.28B excess fuel vs target, $315M recoverable, of which $224M is priced at plant-tier gas cost. Scale cross-check: fouling waste scaled to 100 MW and a 5% deficit gives $0.30M/yr against the spec's ~$1.2M, within an order of magnitude; these plants run at lower CF than the example.
- **Reliability.** Ledger rows keep duration and incidence separate, with explicit exposure months. Hazards use Weibull with delayed entry on age and cum EOH (AIC-comparable) plus a fouling renewal model. Rates use NB/Poisson GLMs with offset log(exposure) and covariates class, log age, log cum EOH, size band, vintage decade, climate region (coastal/arid/industrial/inland), NERC, firm-delivery share, duct burners and CHP. Credibility uses Z = E/(E + φ/λ_pool) with a pool ladder. P12 = 1 − (1+12λ/φ)^−φ. EAL = 12λ·L̄·δ̄·MMBtu/month·gas price. Preventative work is only recommended for wear-out shapes.

## Assumptions register

The full register is in `inputs/assumptions_register.csv` and in the workbook's `assumptions` sheet (28 items, each marked validated / partly / no). The main ones:
- the 2025 file is **Final**, not the early release the spec names;
- NSRDB is replaced by nClimGrid;
- the temperature hinge;
- the peer relaxation ladder;
- the deficit threshold of 0.95;
- the starts proxy is a heuristic (EIA-923 has no start counts);
- cumulative EOH before 2019 is a backlog estimate;
- recovery fractions and remediation costs are unvalidated.

## Data caveats

- 2025 is the first Final release and may still be revised.
- Page 5 prices outside $0.5–50/MMBtu (542 plant-months, up to $562,572) were replaced by the state and then national tier.
- National-tier prices are flagged in `qc_flags` and push a lead to conviction tier C.
- Customer group and SSI/prospect columns are blank because no CRM input was supplied. Owner comes from EIA-860 Schedule 4, or the operating utility as fallback.
- EIA-860 Gas Steam joins at 55% (the spec said ~52%) because coal co-firing units are filed under coal. Treat ST results as indicative.

## Data sources

- EIA-923: `https://www.eia.gov/electricity/data/eia923/` (2019–2024 archive, 2025 current).
- EIA-860: `https://www.eia.gov/electricity/data/eia860/`.
- Fuel cost: `inputs/eia923_page5_gas_fuel_cost_2019_2025.csv` (supplied).
- NOAA nClimGrid county monthly: `climdiv-tmpccy`, `climdiv-pcpncy` from `https://www.ncei.noaa.gov/monitoring-content/data/us/climdiv/monthly/current/`.
- Census county codes: `national_county2020.txt`.
- Natural Earth land-50m via `cdn.jsdelivr.net/npm/world-atlas@2`.
