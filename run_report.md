# Run Report - Solar Underperformance Analysis
Generated: 2026-08-11T18:37:19.608897
**SCOPE: 100-site stratified validation subsample, per the brief's own BUILD ORDER (Section 12). Full 6,204-site scale-up is a tracked follow-up, not yet run.**

## NSRDB access status (READ FIRST)
Track A (NSRDB, PSM v4 GOES Aggregated at developer.nlr.gov) is unreachable from this session's network egress policy - confirmed via `s2_nsrdb.py --preflight-only`, which classifies this precisely as `proxy_denial` (the local egress proxy rejects the CONNECT tunnel before any TLS handshake, not an authentication failure) in under a second. Per the brief's own updated architecture, `s2_nsrdb.py` is now a fully standalone script with no import from the rest of this repo - it is meant to run on a machine with plain internet access (a laptop, a VM, a cron job), not inside this agent sandbox. The full pull is 4,798 cells x 7 years = 33,586 cell-years, a four-day job at the NLR rate limit (1 req/sec, 10,000/day) even once network access exists somewhere. `--dry-run` (no network needed) confirms the exact request list the pull would make. Fixing the sandbox's egress policy would let ad-hoc checks run from here, but the real pull should happen elsewhere regardless.

Weather source used this run: `{'B_clearsky_stopgap': 707}` - i.e. **100% Track B (pvlib Ineichen clear-sky) stopgap**, not measured NSRDB weather. Every PI/PRI/fault/dollar number below inherits this and is NOT decision-grade. Track A code is fully wired (S2, hand-rolled request per the brief's exact parameter spec) and will be used automatically once the environment's network policy allows the NSRDB host.

**API key security note:** the key pasted in chat on 11 August 2026 is treated as compromised per the brief's own Section 11 item 3 and is NOT used anywhere in this codebase - it must be rotated and the replacement set as `NLR_API_KEY` in the environment, never pasted again.

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
- 9167 site-months scored: 179 peer-benchmarked PRI, 8988 physical-fallback (PI_adj) - 2% peer coverage (low at subsample scale by construction; full fleet has much richer peer availability)
- PI distribution: {'count': 4583.0, 'mean': 0.681, 'std': 0.836, 'min': 0.0, '25%': 0.459, '50%': 0.617, '75%': 0.753, 'max': 17.91}

## TEST 11 - Degradation sanity (the best end-to-end check available)
- Median beta_excess at 4+ years of history: **-0.0050** (target ~ -0.0050, i.e. -0.5%/yr)
- Caveat: fit against Track B clear-sky, not measured weather, and on a ~100-site sample where few sites clear the 4-year decision-grade bar. Re-run at full scale (4,396 sites with 4+ years) against real NSRDB data before trusting this number.
- Second caveat, more important than the first: this result should NOT be read as strong validation on its own. S3's E_exp already bakes in the same fixed `d` used to compute beta_excess = beta - d, so beta_excess lands near -d for ANY site whose fitted beta happens to average near zero - which is somewhat construction-driven, not purely an independent recovery of an unknown constant. The genuinely informative part is that beta (not beta_excess) is fit against REAL EIA production data, so it isn't pure tautology - but the exactness of the match here (-0.0050 vs a c-Si-majority fleet's d=0.005) is more consistent with median fleet composition dominating than with a precise physical recovery. Re-validate at full scale before citing this test as proof the pipeline is sound.

## TEST 12 - Over-dispersion (Var/mean by signature)
- BLOCK_OUTAGE: Var/mean = 0.00 - BOS_INTERMITTENT: Var/mean = 0.07 - UNATTRIBUTED: Var/mean = 0.22 
## TEST 22 - Classifier profile sanity (episodes per plant-year)
| signature | this run | reference (Part 7 Step E1) |
|---|---|---|
| UNATTRIBUTED | 0.60 | 0.76 |
| BOS_INTERMITTENT | 0.04 | 0.58 |
| SOILING | 0.00 | 0.31 |
| BLOCK_OUTAGE | 0.01 | 0.29 |

At n~100 sites and Track B weather, large deviation from the reference is EXPECTED and not yet diagnostic of a misconfigured classifier - re-check at full scale against real NSRDB data per the brief's own instruction.

## S9 - Dollars (Section 0.2)
- PRI_P75 (this fleet, 179 peer-benchmarked PRI values): **0.9339**
- Part 8 vs tracker quick-estimate cross-check: 21% of 306 dollar-bearing site-months within 15% of each other. Per the brief, a wide gap points at a peer-set problem, not a rounding difference - and with only 2% peer coverage at subsample scale, that is exactly what this low agreement rate reflects. Expect much tighter agreement at full scale.

## Known limitations this run (encoded as flags, not silently absorbed)
- Track B clear-sky stopgap (see above) - the single biggest caveat on every number.
- G1 (curtailment) BA-month medians computed within the subsample only; rarely reaches the >=3-plants-per-BA-month minimum at this scale.
- Hazard shape uses a bucketed age-band rate, not a full Weibull MLE (too little data at n~100); negative-binomial rate models mostly fail to converge at this scale (see Test 12 table) - both are full-scale-only outputs.
- Vintage-cohort stepwise term (Section 7 identification fix) not fitted here - deferred to the full-scale run where cohort bins have enough sites.
- solar_assets_data.csv was supplied and used (generator-grain time-varying capacity is live, not a placeholder).

## Call list (subsample, Part 8 P75 authoritative $, top 200 site-months)
Written to `output/call_list_subsample.csv` (1131 dollar-bearing site-months total).
