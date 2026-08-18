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
come along with a normal clone - not duplicated here. `pricing.yaml` is
the single source of truth for the Solar SaaS / SCADA Monitoring rates
(fixed at source 17 Aug 2026 - see `tests/test_pricing.py`); both
`explorer.html` and `ceo_cockpit.html` read from it directly rather than
carrying their own copies, so they can never disagree on fee potential.

## One thing the next session needs to know before starting

**Script naming collision.** The spec names the build script
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
