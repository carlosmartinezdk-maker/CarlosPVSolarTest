# CEO Cockpit — handoff package

This directory hands off everything needed to build `ceo_cockpit.html`
(per `spec/CEO_COCKPIT_SPEC.md`) as its own workstream, without needing to
re-run the S0-S17 pipeline that produced it. That pipeline is a multi-day
job (NSRDB weather pull, hourly pvlib modeling across ~6,200 sites) - the
raw inputs it depends on (`nsrdb_cache/`, `data/*.parquet`) are gitignored
and not in this repo, so a fresh clone cannot regenerate them. Everything
in `data/` here is a small, git-committable export instead.

## Contents

- `spec/CEO_COCKPIT_SPEC.md`, `spec/gtm_accounts.csv`, `spec/parent_mapping.csv`
  — the three files Carlos provided, unmodified.
- `data/site_summary.parquet` — one row per site (6,203 sites, the same
  set embedded in `explorer.html` as of this commit), extracted directly
  from that already-tested payload (not recomputed) so it's guaranteed
  consistent with the analyst tool. Columns include site metadata
  (utility, state, mwdc, lat/lon), the PI/PRI monthly series, degradation
  fit (beta/beta_t/beta_excess), routing/ROI fields (cost_of_inaction_usd,
  annual_fee_usd, recommended_offerings, base_offering, rvm_eligible,
  warranty flags), and the reliability fields needed for the account
  pitch pages (`rel_*`: N_blocks, age, 24mo failure probability per
  signature, optimal inspection interval/cost/saving/SCADA value,
  warranty remaining/claim value).
- `data/reliability_fits.json`, `data/hazard_by_age.parquet` — fleet-level
  Weibull fits and the bathtub-curve hazard table, for the Evidence
  screen's hazard curves (these are pooled fleet-wide fits, not
  decomposable by account - same caveat as in `explorer.html`'s
  Reliability tab).

`pricing.yaml` and `config.py` are already tracked in the main repo and
come along with a normal clone - not duplicated here.

## Two things the next session needs to know before starting

**1. The 12x pricing bug in spec Section 1.1 is real, and `pricing.yaml`
is shared with the main pipeline.** Solar SaaS and SCADA Monitoring are
priced per MWdc per MONTH, not per year - `pricing.yaml` currently has
them as flat annual rates, which is wrong by 12x. Every `annual_fee_usd`,
`roi_multiple`, and `cost_of_inaction_usd`-vs-fee comparison already in
`explorer.html`, `SSI_Solar_Reliability_Metrics.xlsx`, and this handoff's
`site_summary.parquet` inherits that error. Fixing `pricing.yaml` for the
cockpit (as the spec requires) will change those numbers everywhere else
too, the next time the main pipeline is rebuilt. **Flag this back to
Carlos explicitly rather than silently fixing it in isolation** - he
should decide whether/when the main analysis branch re-runs S9-S17 with
corrected pricing, since that's a larger, separate action from building
the cockpit.

**2. Script naming collision.** The spec names the build script
`s12_ceo_cockpit.py`, but `s12_lifedata.py` already exists in this repo
(life-data construction, part of the S12-S17 reliability addendum built
earlier). Use `s18_ceo_cockpit.py` instead, continuing the existing
numbering, so nothing gets overwritten.

## Suggested workflow

This is meant to be its own branch and its own PR, built on top of this
commit, so it doesn't collide with ongoing work on the main analysis
branch. `explorer.html` stays the analyst tool; `ceo_cockpit.html` is a
new, separate deliverable per the spec's own framing ("a second HTML, not
a replacement").
