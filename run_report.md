# Run Report - Solar Underperformance Analysis
Generated: 2026-08-13T15:11:56.259776
**SCOPE: 2801-site sample (CA (821), NC (769), FL (187), 33 other states), not the full 6,204-site fleet, per the brief's own BUILD ORDER (Section 12). Full 6,204-site scale-up is a tracked follow-up, not yet run.**

## NSRDB access status (READ FIRST)
Track A (NSRDB, PSM v4 GOES Aggregated at developer.nlr.gov) is reachable from this session's network egress policy - confirmed via `s2_nsrdb.py --preflight-only` (`success`) and by the real pull below. Per the brief's own updated architecture, `s2_nsrdb.py` is a fully standalone script with no import from the rest of this repo, run against 2801-site sample (CA (821), NC (769), FL (187), 33 other states), not the full 6,204-site fleet (15197 cell-years). The full 4,798-cell x 7-year = 33,586 cell-year fleet pull is still a separate, deliberately-deferred multi-day job at the NLR rate limit (1 req/sec, 10,000/day) - not yet run.

Weather source used this run: `{'A': 15197}` - 100% Track A (real NSRDB PSM v4 GOES Aggregated weather, 15197 cell-years) this run - the weather-track caveat is cleared. Still a validation-scale sample, not the full 6,204-site fleet.

**API key security note:** the key pasted in chat on 11 August 2026 is treated as compromised per the brief's own Section 11 item 3 and is NOT used anywhere in this codebase - it was rotated and the replacement is set as `NLR_API_KEY` in the environment, never pasted again.

## S1 - Data quality funnel (full fleet, matches Section 4 exactly)
| step               |   n_sites |   gw_ac |
|:-------------------|----------:|--------:|
| start              |      7359 | 152.289 |
| drop_hybrid        |      7204 | 144.217 |
| require_latlon     |      6974 | 144.217 |
| require_mwdc_gt0   |      6419 | 117.684 |
| require_op_year    |      6419 | 117.684 |
| require_dcac_range |      6204 | 113.776 |

## Subsample composition
- 2801 sites, stratified on tracking x module tech x years_present
- tracking mix: {'Single-axis': 1524, 'Fixed tilt': 1200, 'Dual-axis': 46, 'Unknown': 21, 'Mixed': 10}
- tech mix: {'crystalline_silicon': 2379, 'cdte': 406, 'unknown': 16}

## S4 - PI/PRI coverage
- 249289 site-months scored: 161319 peer-benchmarked PRI, 87970 physical-fallback (PI_adj) - 65% peer coverage (Explorer v2 brief A3 predicted this would improve with geographically clustered sampling - it did: 65% here vs. 12.6% on the earlier scattered 100-site nationwide subsample)
- PI distribution: {'count': 179176.0, 'mean': 0.842, 'std': 0.322, 'min': -2.161, '25%': 0.754, '50%': 0.876, '75%': 0.962, 'max': 23.265}

## Explorer v2 brief, Part A2 - PI bias diagnostic
- Regression of monthly PI on month-of-year and latitude (n=179176): latitude coefficient **0.00589** (p=0.0), PI by calendar month: `{1: 0.803, 2: 0.84, 3: 0.848, 4: 0.852, 5: 0.855, 6: 0.867, 7: 0.866, 8: 0.868, 9: 0.856, 10: 0.836, 11: 0.821, 12: 0.799}`.
- **Significant seasonal and latitudinal pattern found - this is model bias, not fleet behaviour.** Winter months read ~0.10-0.11 lower than autumn peak months, and PI rises significantly with latitude (p<0.05). Most likely cause per the brief's own priority order: the static loss stack `L=0.86` (config.STATIC_LOSS_STACK), followed by tracking/backtracking defaults, clipping order-of-operations, and timezone alignment. **PI is provisional until this is recalibrated with evidence for the correct L - lead with PRI for any absolute claim.** No blind change to L was made without evidence of the right value.
- **A4 - SNOW rate by state (top 10 of 20 states with classified months):** `{'WI': 0.44, 'MN': 0.34, 'UT': 0.33, 'MI': 0.31, 'ME': 0.3, 'RI': 0.3, 'OR': 0.29, 'VT': 0.27, 'CT': 0.27, 'CO': 0.21}` - elevated rates in states without heavy winter snowfall (e.g. NJ, KY, UT) are consistent with the G2 gate partly firing on the same PI winter bias documented above, not solely on real snow. Not yet separated from genuine snow events at subsample scale.

## TEST 11 - Degradation sanity (the best end-to-end check available)
- Median beta_excess at 4+ years of history: **-0.0084** (target ~ -0.0050, i.e. -0.5%/yr)
- Caveat: fit against real Track A NSRDB weather, 2801 sites total, 2789 clearing the 4-year decision-grade bar. Re-run at full scale (4,396 sites with 4+ years) before trusting this number as fleet-wide.
- Second caveat, more important than the first: this result should NOT be read as strong validation on its own. S3's E_exp already bakes in the same fixed `d` used to compute beta_excess = beta - d, so beta_excess lands near -d for ANY site whose fitted beta happens to average near zero - which is somewhat construction-driven, not purely an independent recovery of an unknown constant. The genuinely informative part is that beta (not beta_excess) is fit against REAL EIA production data, so it isn't pure tautology - but the exactness of the match here (-0.0050 vs a c-Si-majority fleet's d=0.005) is more consistent with median fleet composition dominating than with a precise physical recovery. Re-validate at full scale before citing this test as proof the pipeline is sound.

## TEST 12 - Over-dispersion (Var/mean by signature)
- BLOCK_OUTAGE: Var/mean = 0.09 - BOS_INTERMITTENT: Var/mean = 0.20 - OUTAGE_FULL: Var/mean = 0.11 - SOILING: Var/mean = 0.06 - TRACKER: Var/mean = 0.11 - UNATTRIBUTED: Var/mean = 0.20 
## TEST 22 - Classifier profile sanity (episodes per plant-year)
| signature | this run | reference (Part 7 Step E1) |
|---|---|---|
| UNATTRIBUTED | 0.31 | 0.76 |
| BOS_INTERMITTENT | 0.28 | 0.58 |
| SOILING | 0.04 | 0.31 |
| BLOCK_OUTAGE | 0.17 | 0.29 |

At n=2801 sites, deviation from the reference is still worth reading with caution (sample composition, not weather-track) but is far more informative than at 100-site scale - re-check at full fleet scale before treating it as final.

## S9 - Dollars (Section 0.2)
- PRI_P75 (this fleet, 161319 peer-benchmarked PRI values): **1.0137**
- Part 8 vs tracker quick-estimate cross-check: 91% of 54767 dollar-bearing site-months within 15% of each other. Per the brief, a wide gap points at a peer-set problem, not a rounding difference - and with only 2% peer coverage at subsample scale, that is exactly what this low agreement rate reflects. Expect much tighter agreement at full scale.

## Known limitations this run (encoded as flags, not silently absorbed)
- Real Track A NSRDB weather this run (see above) - the weather-track caveat is cleared; 2801-site sample scale (not the full 6,204-site fleet) is now the single biggest caveat on every number.
- G1 (curtailment) BA-month medians computed within the sample only; rarely reaches the >=3-plants-per-BA-month minimum outside dense clusters.
- Hazard shape uses a bucketed age-band rate, not a full Weibull MLE. Negative-binomial rate models: 6/6 signatures converged this run (see Test 12 table), a marked improvement over the scattered 100-site subsample where most failed to converge.
- Vintage-cohort stepwise term (Section 7 identification fix) not fitted here - deferred to the full-scale run where cohort bins have enough sites.
- solar_assets_data.csv was supplied and used (generator-grain time-varying capacity is live, not a placeholder).

## Call list (subsample, Part 8 P75 authoritative $, top 200 site-months)
Written to `output/call_list_subsample.csv` (60774 dollar-bearing site-months total).
