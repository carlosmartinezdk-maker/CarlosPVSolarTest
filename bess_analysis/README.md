# BESS fleet health, efficiency and reliability (EIA-923 monthly, 2019–2025)

This builds the spec in `../specs/bess_analysis_prompt.md` (v2) for every US grid-scale battery (EIA-923 *Page 1 Energy Storage*, prime mover `BA`, fuel `MWH`). It anchors on **efficiency, not throughput**: battery output is a dispatch decision, so low throughput is not a fault by default (Guardrail 1).

The core method is the **auxiliary-load decomposition**. For site *i*, month *m* with `h` hours:

```
Charge/Discharge = 1/eta_true + P_aux * (h / Discharge)      # per-site OLS across usable months
```

The intercept gives the conversion efficiency (cells + PCS) and the slope gives the continuous parasitic load (BMS, HVAC, standby). **No dollar figures appear anywhere.** Lost battery MWh have no PPA price, and monetising them needs nodal price data this build does not have (Guardrail 6).

## Run

```bash
# needs the same data/ layout as gas_analysis (EIA-923 + EIA-860 2019-2025, nClimGrid county files);
# the hybrid PV check reads the Page 1 cache that gas_analysis/load_923.py builds.
python load_storage.py && python load_860_allvintages.py && python panel.py --force
python run.py            # ~40 s; prints the gate table, exits 1 on any hard FAIL
```

The modules follow the spec: `load_storage.py`, `load_860_allvintages.py`, `hybrid_filter.py`, `weather.py`, `panel.py`, `efficiency_decomp.py`, `peers.py`, `signatures.py`, `ledger.py`, `hazard.py`, `reliability.py`, `leads.py`, `report.py` and `run.py`. Every threshold is a named constant.

## Deliverables (`outputs/`)

| File | Content |
|---|---|
| `bess_monthly.parquet` | 37,452 plant-months, 988 sites. Charge, Discharge, RTE, EFC, UTI (+ peer EFC, tier), E_rated (time-varying), Duration and band, T_amb, cum_EFC, throughput_used, signature, MWh at stake, recoverable MWh, RTE points lost, hybrid and in-service flags, quality_flags |
| `bess_efficiency_decomposition.csv` | one row per site: η_true, P_aux (MW and % of nameplate), P_aux summer/shoulder/winter, HVAC excess, rolling-refit trends in η and P_aux, naive RTEs, n, R², standard errors, `insufficient_history` where applicable |
| `bess_event_ledger.parquet` | plant × year × signature: duration D, incidence K, exposure months, MWh at stake, recoverable MWh, ledger type, L̄ |
| `bess_episodes.parquet` | one row per episode |
| `bess_site_summary.xlsx` | site summary (annual RTE/EFC/UTI, η_true, P_aux, fade, cumulative EFC, warranty position, availability months, dominant signature, applications, chemistry, enclosure, owner, hybrid flag, P12/EAL per fault signature, lead rank), plus sheets for leads, gates, decomposition, hazards, rate models, backtest, risk, hybrid quarantine and assumptions |
| `efficiency_decomposition.png` | η_true vs P_aux by duration band, standalone vs hybrid, with fleet medians and the naive-RTE line |
| `hazard_curves.png` | Weibull onset hazards on calendar age vs cumulative EFC |
| `bess_leads.csv` | 464 sites (135 tier A, 64 tier B, 265 tier C), ranked by MWh at stake over the last 24 months and then by warranty headroom |
| `hybrid_quarantine.csv` | the 515 quarantined hybrid sites and the reason each was flagged |
| `gate_results.csv`, `run_log.txt` | gate table and the full console output |

## Acceptance gates (last run)

| Check | Expected | Got | Status | Note |
|---|---|---|---|---|
| Fleet median apparent RTE 2025, standalone (site annual D/C) | 0.851 ±0.02 | 0.84 | **PASS** | median of monthly RTE 0.842; throughput-weighted 0.855 |
| Decomposed eta_true, fleet median | 0.889 ±0.02 | 0.889 | **PASS** | p10 0.778, p90 0.954; standalone only 0.888 |
| Naive RTE on the same fitted sites (site mean of monthly RTE) | 0.844 ±0.02 | 0.84 | **PASS** | throughput-weighted per site 0.854 |
| Gap eta_true - naive (points) | ~4.5 ±1.5 | 4.87 | **PASS** | with throughput-weighted naive: 3.42 |
| eta_true above naive RTE (regression not inverted) | True | True | **PASS** |  |
| P_aux % of nameplate, median | 0.21 (p90 < ~1%) | 0.221 | **PASS** | p10 -0.07%, p90 0.84% |
| Sites with a usable aux decomposition | ~600 of ~960 | 623 of 988 | **PASS** |  |
| Total BESS discharge 2025 (MWh) | 26,500,000 ±1,000,000 | 26,706,620 | **PASS** |  |
| Total BESS discharge 2019 (MWh) | 430,000 ±30,000 | 456,006 | **PASS** |  |
| BESS nameplate 2025 (GW, EIA-860 3_4 BA) | ~40-43 | 44.0 | **WARN** | year-end operable incl. units commissioned late 2025 |
| Median duration 2025 (h) | 2.0 | 2.0 | **PASS** |  |
| Capacity join rate to EIA-860 (plant-months) | >=0.98 | 0.9942 | **PASS** | same-vintage 0.9837 |
| Fleet RTE vs EIA published anchor (standalone 2025, throughput-weighted) | ~0.82-0.85 (and <0.95) | 0.855 | **PASS** | above 0.95 would mean hybrids included or Quantity/Grossgen swapped |
| Variance/mean of fault counts, FULL_OUTAGE | >1 (overdispersion -> NB) | 1.1 | **WARN** | NB alpha=0.000; used: poisson (alpha~0) |
| Variance/mean of fault counts, PARTIAL_AVAILABILITY | >1 (overdispersion -> NB) | 0.93 | **WARN** | NB alpha=0.000; used: poisson (alpha~0) |
| Variance/mean of fault counts, THERMAL_AUX | >1 (overdispersion -> NB) | 1.18 | **WARN** | NB alpha=1.041; used: negative binomial |
| Variance/mean of fault counts, UNATTRIBUTED | >1 (overdispersion -> NB) | 1.26 | **WARN** | NB alpha=0.000; used: poisson (alpha~0) |
| Backtest FULL_OUTAGE (fit<=Y, predict Y+1, 2023-2025) | AUC>0.65, slope~1, chi2/df~1, beats mean | AUC 0.63, slope 0.65, chi2/df 3.9 | **WARN** | 40% of test plant-years are sites with no prior history; beats mean: True |
| Backtest PARTIAL_AVAILABILITY (fit<=Y, predict Y+1, 2023-2025) | AUC>0.65, slope~1, chi2/df~1, beats mean | AUC 0.61, slope 0.48, chi2/df 11.3 | **WARN** | 40% of test plant-years are sites with no prior history; beats mean: False |
| Backtest THERMAL_AUX (fit<=Y, predict Y+1, 2023-2025) | AUC>0.65, slope~1, chi2/df~1, beats mean | AUC 0.74, slope 0.83, chi2/df 3.9 | **WARN** | 40% of test plant-years are sites with no prior history; beats mean: True |
| Backtest UNATTRIBUTED (fit<=Y, predict Y+1, 2023-2025) | AUC>0.65, slope~1, chi2/df~1, beats mean | AUC 0.61, slope 0.41, chi2/df 6.2 | **WARN** | 40% of test plant-years are sites with no prior history; beats mean: False |

**Summary: 12 PASS, 9 WARN, 0 FAIL.** Every quantitative validation point in the spec reproduces:
- η_true median 0.889 (spec 0.889), p10 0.778 (0.775), p90 0.954 (0.956);
- P_aux median 0.22% of nameplate (0.21%), p10 −0.07% (−0.07%), p90 0.84% (0.85%);
- 623 fitted sites (spec 607);
- 2025 discharge 26.7 TWh (26.5);
- 2019 discharge 456 GWh (430);
- median duration 2.0 h.

## Findings and caveats

1. **The naive-RTE definition matters.** The spec's 0.844 is reproduced by the **per-site mean of monthly apparent RTE** (0.840), giving a gap of 4.9 points. That mean is pulled down by low-throughput months, where parasitic load dominates. A throughput-weighted naive RTE per site gives 0.854 and a gap of 3.4 points. Both are reported; the spec does not say which it meant.
2. **Most of the fleet is hybrid.** 515 of 988 sites are quarantined:
   - PV under the same Plant Id: 459;
   - RTE > 1 in some month: 121;
   - DC-coupled: 106;
   - co-located renewable firming: 88.

   Standalone and all-site η_true are almost identical (0.888 vs 0.889). Hybrid apparent RTE runs higher (2025 median 0.854 vs 0.840), which is consistent with unreported charging from PV.
3. **Annual respondents.** Most battery plant-years in 2019–2022 are EIA-923 annual respondents, whose monthly values are EIA allocations. They are excluded from the regression and from monthly signatures (`ANNUAL_RESPONDENT`). This is the same data trap found in the gas build.
4. **Pre-commissioning rows look like outages.** EIA-923 carries a zero row for every month of a new plant's first year. Without an in-service window, 7,247 site-months read as "full outages"; after it (first active month onward, trailing zeros kept unless the site is retired), 1,737 remain.
5. **Throughput at stake in 2025**, all sites, MWh:

   | Signature | MWh | Note |
   |---|---|---|
   | under-dispatch | 1,349,000 | commercial, not technically fixable |
   | full outage | 199,000 | |
   | unattributed | 126,000 | |
   | partial availability | 111,000 | |
   | thermal/aux | 50,000 | |
   | cell degradation | 13,000 | |
   | capacity fade | 6,000 | |

   As the spec predicted, the commercial bucket dwarfs the technical ones.
6. **Hazard shapes.**
   - **Full outages are wear-out against calendar age**: k = 1.22 [1.10, 1.35], and age fits far better than cumulative EFC by AIC. The spec expected infant mortality, so this is a surprise. It may reflect a fleet whose older (2019–2021) sites are now seeing more outages, including incidents such as the 2025 Moss Landing fire, which shows up as a low-η/low-UTI lead.
   - Partial availability is random (k = 1.07).
   - Thermal/aux (k = 0.32) and unattributed (k = 0.43) show infant mortality.
   - Calendar age beats throughput as the time axis for every signature, so the data do not support throughput-based warranty timing as the better physical clock.
7. **Dispersion and backtest.** Fault counts are only mildly overdispersed (variance/mean 0.9–1.3). Only thermal/aux gets NB α > 0. The Y→Y+1 backtest (2023–2025) reaches AUC 0.61–0.74, but calibration slopes are 0.41–0.83 and 40% of test plant-years are sites with no prior history. **The history requirement fails for most sites, as the spec expected; do not use the λ/P12 figures as forecasts yet.**
8. **Degradation.**
   - **η trend:** 363 sites with at least 24 months of history have a rolling-refit η trend, with a median of −0.8 points/yr. This is noisy; per-site standard errors are in the CSV.
   - **Fade:** the EPC fade slope is `insufficient_history` for 449 sites and has a median of 0.0%/yr where computable, so there is no fleet fade signal yet. That matches the spec's expectation for a fleet with a median age of 2–3 years.
9. **Decomposition caveat.** Within a site, the intercept and slope estimates are negatively correlated. The fleet medians are robust, but an individual site's (η_true, P_aux) pair should be read with its standard errors (`se_a`, `se_b`).
10. **Nameplate 2025 = 44.0 GW** (spec ~40–43, WARN). EIA-860 year-end operable capacity includes units commissioned in late 2025 that have little 2025 throughput.

## What monthly data cannot determine

- **The measurement boundary.** η_true is closer to the conversion boundary and apparent RTE is the grid-interface boundary. Neither is a cell-level figure: cell LFP RTE is above 95%.
- **State of charge.** Month-end state of charge is unknown, which is why months with |D − C|/C > 0.5 are flagged as SOC drift.
- **Real outages vs dispatch.** Monthly data cannot fully separate a real outage from a correct decision not to dispatch. Peer UTI in the same BA only narrows the gap.
- **Peak power.** Realised charge/discharge asymmetry uses monthly average power as a proxy.
- **Warranty position.** Cycle life (6,000 assumed), the SOC envelope and augmentation schedules are contractual and not public. `throughput_used` and `envelope_breach` rest on stated assumptions.
- **Commercial value of a cycle.** This needs nodal prices.

## Assumptions register

The full register is in `inputs/assumptions_register.csv` (24 items) and the workbook's `assumptions` sheet. The main ones:
- the 2025 file is **Final**, not the early release;
- seasonal P_aux is fitted with one shared intercept;
- the naive-RTE definition;
- the UTI peer ladder, needing at least 3 healthy peers;
- the in-service window;
- the partial-availability fraction set;
- hybrids skip efficiency-based rules 4–6;
- 6,000-cycle warranty and a −10 to 30 °C ambient envelope;
- nClimGrid county temperature in place of NSRDB.
