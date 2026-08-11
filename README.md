# Solar Underperformance Analysis (PI / PRI / Degradation / Faults)

Build brief: `CLAUDE_CODE_BRIEF_PI_PRI_Analysis_1.md` (v2, 2019-2026 panel). That
document is the authority on methodology, constants, and acceptance tests;
this README only tracks build status.

## Status

**Built and tested (39/39 tests passing, `python3 -m pytest tests/`):**

| File | Covers |
|---|---|
| `config.py` | Every constant from the brief (Sections 6), nothing inline elsewhere |
| `s2_nsrdb.py` | Standalone NLR (National Laboratory of the Rockies, formerly NREL) NSRDB pull -- preflight check, `--dry-run`, resumable parquet cache, grid dedup, rate limiting. No dependency on the rest of this repo, by design (Section 5/12) |
| `s6_signatures.py` | D-Band classifier core: elimination gates, band/deficit, block-fraction nearest-match, discriminators, confidence, LOW-confidence relabel |
| `s9_dollars.py` | Index-to-dollars formulas, including the zero-recovery guardrail for CURTAILMENT/SNOW/CLIPPING |
| `tests/` | Acceptance tests 9, 15, 17, 18, 19, 20, 21, 24, 29, 32 from Section 10, plus a regression test for a proxy-tunnel failure mode found during development (see below) |

**Not yet built:** `s0_load.py`, `s1_gates.py`, `s3_model.py`, `s4_indices.py`,
`s5_decision.py`, `s7_trajectory.py`, `s8_ledger.py`, `s10_report.py`,
`s11_explorer.py`. These all operate on the source data files (`production_long.csv`,
`site_master.csv`, `solar_assets_data.csv`, the FY19-FY26 workbook), none of
which exist in this repo yet. Building and testing them against nothing would
produce exactly the kind of unverified code the brief warns against (see its
own Test 11 philosophy: "the method recovering a physical constant it was
never given means the pipeline is sound" -- that only works with real data
to check against). **Next step once the data files land:** `s0_load.py` and
`s1_gates.py` first, validated against the Section 4 funnel counts, then the
rest in the brief's stated execution order (S0→S1→S2→S3→S4→S5→S7→S6→S8→S9→S10→S11).

## The NLR domain

`developer.nlr.gov` was verified independently (DOE's own site, multiple
news outlets, live NLR documentation pages matching this brief's endpoint
specs) -- NREL was renamed the National Laboratory of the Rockies on 1 Dec
2025. This is real, not a spoofed lookalike domain. See commit history for
the verification trail.

The agent sandbox this repo is developed in blocks egress to
`developer.nlr.gov` by an organization-level policy (403 on the CONNECT
tunnel, confirmed both via `curl` and via `s2_nsrdb.py preflight`). That is
expected and by design: **`s2_nsrdb.py` is meant to run outside this
sandbox**, per the brief's own Section 5/12 architecture. Run it on any
machine with normal internet access:

```bash
export NLR_API_KEY=...           # see rotation note below -- do this first
python3 s2_nsrdb.py preflight     # confirms reachability + auth before the real pull
python3 s2_nsrdb.py pull --sites site_master.csv --cache-dir nsrdb_cache \
    --email you@example.com --dry-run   # see the plan first
python3 s2_nsrdb.py pull --sites site_master.csv --cache-dir nsrdb_cache \
    --email you@example.com             # the real (multi-day) pull
```

## Action required: rotate the NLR API key

The brief states the key issued 11 August 2026 was shared in plain text over
chat and must be treated as compromised (Section 11, item 4). Reissue it at
`https://developer.nlr.gov/signup/`, set the new value as `NLR_API_KEY`, and
don't paste a key into a document, ticket, or chat message again. Nothing in
this repo reads a key from anywhere but the environment (`config.get_api_key()`
/ `s2_nsrdb.api_key()`), so rotating it is a drop-in, no code change needed.

## Testing

```bash
pip install pytest
python3 -m pytest tests/ -v
```
