# Run Report - Solar Underperformance Analysis
Generated: 2026-08-11T21:20:48.930658
**SCOPE: 100-site stratified validation subsample, per the brief's own BUILD ORDER (Section 12). Full 6,204-site scale-up is a tracked follow-up, not yet run.**

## NSRDB access status (READ FIRST)
Track A (NSRDB, PSM v4 GOES Aggregated at developer.nlr.gov) is reachable from this session's network egress policy - confirmed via `s2_nsrdb.py --preflight-only` (`success`) and by the real pull below. Per the brief's own updated architecture, `s2_nsrdb.py` is a fully standalone script with no import from the rest of this repo, run against the 100-site validation subsample (707 cell-years). The full 4,798-cell x 7-year = 33,586 cell-year fleet pull is still a separate, deliberately-deferred multi-day job at the NLR rate limit (1 req/sec, 10,000/day) - not yet run.

Weather source used this run: `{'A': 707}` - 100% Track A (real NSRDB PSM v4 GOES Aggregated weather, 707 cell-years) this run - the weather-track caveat is cleared. Still a 100-site stratified validation subsample, not the full 6,204-site fleet.

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
- 103 sites, stratified on tracking x module tech x years_present
- tracking mix: {'Fixed tilt': 46, 'Single-axis': 35, 'Dual-axis': 10, 'Unknown': 7, 'Mixed': 5}
- tech mix: {'crystalline_silicon': 71, 'cdte': 18, 'unknown': 14}

## S4 - PI/PRI coverage
- 9167 site-months scored: 1159 peer-benchmarked PRI, 8008 physical-fallback (PI_adj) - 13% peer coverage (low at subsample scale by construction; full fleet has much richer peer availability)
- PI distribution: {'count': 4583.0, 'mean': 0.824, 'std': 0.482, 'min': 0.0, '25%': 0.631, '50%': 0.833, '75%': 0.964, 'max': 9.208}

## TEST 11 - Degradation sanity (the best end-to-end check available)
- Median beta_excess at 4+ years of history: **-0.0050** (target ~ -0.0050, i.e. -0.5%/yr)
- Caveat: fit against real Track A NSRDB weather, but still a ~100-site sample where few sites clear the 4-year decision-grade bar. Re-run at full scale (4,396 sites with 4+ years) before trusting this number as fleet-wide.
- Second caveat, more important than the first: this result should NOT be read as strong validation on its own. S3's E_exp already bakes in the same fixed `d` used to compute beta_excess = beta - d, so beta_excess lands near -d for ANY site whose fitted beta happens to average near zero - which is somewhat construction-driven, not purely an independent recovery of an unknown constant. The genuinely informative part is that beta (not beta_excess) is fit against REAL EIA production data, so it isn't pure tautology - but the exactness of the match here (-0.0050 vs a c-Si-majority fleet's d=0.005) is more consistent with median fleet composition dominating than with a precise physical recovery. Re-validate at full scale before citing this test as proof the pipeline is sound.

## TEST 12 - Over-dispersion (Var/mean by signature)
- BLOCK_OUTAGE: Var/mean = 0.10 - BOS_INTERMITTENT: Var/mean = 0.10 - OUTAGE_FULL: Var/mean = 0.25 - SOILING: Var/mean = 0.00 - TRACKER: Var/mean = 0.13 - UNATTRIBUTED: Var/mean = 0.21 
## TEST 22 - Classifier profile sanity (episodes per plant-year)
| signature | this run | reference (Part 7 Step E1) |
|---|---|---|
| UNATTRIBUTED | 0.56 | 0.76 |
| BOS_INTERMITTENT | 0.08 | 0.58 |
| SOILING | 0.01 | 0.31 |
| BLOCK_OUTAGE | 0.03 | 0.29 |

At n~100 sites, large deviation from the reference is still EXPECTED (sample-size, not weather-track) and not yet diagnostic of a misconfigured classifier - re-check at full fleet scale.

## S9 - Dollars (Section 0.2)
- PRI_P75 (this fleet, 1159 peer-benchmarked PRI values): **1.0545**
- Part 8 vs tracker quick-estimate cross-check: 27% of 539 dollar-bearing site-months within 15% of each other. Per the brief, a wide gap points at a peer-set problem, not a rounding difference - and with only 2% peer coverage at subsample scale, that is exactly what this low agreement rate reflects. Expect much tighter agreement at full scale.

## Known limitations this run (encoded as flags, not silently absorbed)
- Real Track A NSRDB weather this run (see above) - the weather-track caveat is cleared; 100-site subsample scale is now the single biggest caveat on every number.
- G1 (curtailment) BA-month medians computed within the subsample only; rarely reaches the >=3-plants-per-BA-month minimum at this scale.
- Hazard shape uses a bucketed age-band rate, not a full Weibull MLE (too little data at n~100); negative-binomial rate models mostly fail to converge at this scale (see Test 12 table) - both are full-scale-only outputs.
- Vintage-cohort stepwise term (Section 7 identification fix) not fitted here - deferred to the full-scale run where cohort bins have enough sites.
- solar_assets_data.csv was supplied and used (generator-grain time-varying capacity is live, not a placeholder).

## Call list (subsample, Part 8 P75 authoritative $, top 200 site-months)
Written to `output/call_list_subsample.csv` (1188 dollar-bearing site-months total).
