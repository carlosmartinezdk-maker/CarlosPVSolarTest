"""
Recovery benchmark - switchable P50 / P75 / Golden year targets
(RECOVERY_BENCHMARK_AND_CUSTOMER_ROI.md Part 1).

Reads the pipeline's own site-month parquet directly (same source S9/S11
read, not a re-derivation) and produces one small per-site table with
everything a client-side toggle needs: the four fleet-wide percentiles
(PRI/PI x P50/P75, already the "Conservative"/"Attainable" settings) and,
per site, the "Proven" (golden year) target with every required guard
already applied - floor, cap, degradation basis, and the fallback/already-
at-best flags a consumer must check before using it.

Deliberately NOT computing month-by-month dollar figures here: §1.2's own
point is that the toggle is "cheap enough to run client-side" against the
E_act/PRI/PI/rec_pct/signature arrays the explorer and cockpit payloads
already carry per site-month. This module only produces the handful of
site-level and fleet-level SCALARS those clients need to pick a target.
"""
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s RB %(message)s")
log = logging.getLogger("recovery_benchmark")

MONTHLY_SRC = "data/site_month_dollars.parquet"
SITES_SRC = "data/subsample_sites.parquet"

CAPACITY_SUSPECT_PI_THRESHOLD = config.CAPACITY_SUSPECT_PI_THRESHOLD
GOLDEN_MIN_MONTHS_IN_YEAR = config.GOLDEN_MIN_MONTHS_IN_YEAR
GOLDEN_MIN_YEARS_HISTORY = config.GOLDEN_MIN_YEARS_HISTORY
GOLDEN_CAP_PRI = config.GOLDEN_CAP_PRI


def compute_percentiles(df: pd.DataFrame) -> dict:
    """Same methodology as s9_dollars.compute_pri_p75/compute_pi_p75,
    extended to also return P50 - PRI restricted to peer-benchmarked
    months (PRI is null on physical-fallback months anyway), PI over every
    scored month regardless of mode."""
    peer_pri = df.loc[df["benchmark_mode"] == "peer", "PRI"].dropna()
    all_pi = df["PI"].dropna()
    return dict(
        pri_p50=float(peer_pri.quantile(0.50)) if len(peer_pri) else None,
        pri_p75=float(peer_pri.quantile(0.75)) if len(peer_pri) else None,
        pi_p50=float(all_pi.quantile(0.50)) if len(all_pi) else None,
        pi_p75=float(all_pi.quantile(0.75)) if len(all_pi) else None,
    )


def compute_capacity_suspect(df: pd.DataFrame) -> pd.Series:
    """Trailing-12-scored-month median PI > 1.35 -> the MWdc denominator is
    almost certainly wrong, not the plant overperforming by 35%+. Same rule
    the cockpit used locally (s18_ceo_cockpit.flag_capacity_suspect) -
    promoted here so it's computed once, pipeline-level, and every
    downstream consumer (including the golden-year guard below, which
    needs it) reads the same flag instead of a second copy that can drift."""
    out = {}
    for site, g in df.sort_values("month_start").groupby("site", sort=False):
        vals = g["PI"].tail(12).dropna().tolist()
        median_pi = float(np.median(vals)) if vals else np.nan
        out[site] = bool(median_pi > CAPACITY_SUSPECT_PI_THRESHOLD) if not np.isnan(median_pi) else False
    return pd.Series(out, name="capacity_suspect")


def _degradation_rate(tech_class: str) -> float:
    return config.DEGRADATION_RATE_ANNUAL.get(tech_class, config.DEGRADATION_RATE_ANNUAL["crystalline_silicon"])


def compute_golden_year(df: pd.DataFrame, sites: pd.DataFrame, capacity_suspect: pd.Series,
                         pri_p50: float, pi_p50: float) -> pd.DataFrame:
    """§1.3 - for each site, the calendar year with the highest mean PRI
    among years with >=6 PRI-scored months. Then, in order:
      1. capacity_suspect sites never get a golden year (excluded outright)
      2. fewer than 2 qualifying years -> no golden year, fall back to P75
      3. cap PRI_golden at 1.20 (flag if it hit the cap)
      4. floor at PRI_P50 (REQUIRED - §1.3's own finding is that an
         unfloored golden year is a *weaker* target than P75 on half the
         fleet, which would quietly understate the opportunity on exactly
         the accounts most worth selling to)
      5. compute the same year's mean PI (any month, not just physical-
         fallback ones - PI is defined whenever E_act/E_exp exist,
         independent of that month's benchmark mode) as the equivalent
         target for physical-fallback months, same cap/floor treatment
      6. flag "already at best" when the golden year is also the site's
         most recent year with scored data - recoverable there is ~0 by
         construction, which must read as "already at its best", not $0
    Degradation adjustment itself is NOT applied here (it's a function of
    the month being evaluated, not a single per-site scalar) - this
    returns the ingredients (golden_year, floored targets, degradation
    rate) for the client/consumer to apply
    PRI_target_golden_adj(m) = pri_golden_floored * (1-d)**(year(m)-golden_year).
    """
    tech = sites.set_index("site")["tech_class"]
    rows = []
    for site, g in df.groupby("site", sort=False):
        suspect = bool(capacity_suspect.get(site, False))
        scored = g[g["PI"].notna() | g["PRI"].notna()]
        latest_year = int(scored["year"].max()) if len(scored) else None

        # Which year was "best" is decided on `score` - the pipeline's own
        # unified performance metric (S4/S5: PRI where peer-benchmarked,
        # PI_adj where physical-fallback), not PRI alone. Restricting this
        # to PRI-only would silently exclude every site that has never had
        # a peer group (permanently physical-fallback), which is exactly
        # the "golden-year equivalent on PI" case §1.2 says cannot be
        # skipped. PRI_golden/PI_golden themselves are still computed
        # separately below, each from its own mode's months.
        score_by_year = g[g["score"].notna()].groupby("year")
        qualifying = {yr: sub["score"].mean() for yr, sub in score_by_year if len(sub) >= GOLDEN_MIN_MONTHS_IN_YEAR}

        if suspect or len(qualifying) < GOLDEN_MIN_YEARS_HISTORY:
            rows.append(dict(
                site=site, golden_available=False,
                golden_reason="capacity_suspect" if suspect else "insufficient_history",
                golden_year=None, pri_golden_raw=None, pri_golden_capped=None, pri_golden_capped_flag=False,
                pri_golden_floored=None, pi_golden_floored=None, degradation_rate_annual=_degradation_rate(tech.get(site)),
                already_at_best=False,
            ))
            continue

        golden_year = max(qualifying, key=qualifying.get)

        pri_same_year = g.loc[(g["year"] == golden_year) & g["PRI"].notna(), "PRI"]
        if len(pri_same_year):
            pri_raw = float(pri_same_year.mean())
            capped_flag = pri_raw > GOLDEN_CAP_PRI
            pri_capped = min(pri_raw, GOLDEN_CAP_PRI)
            pri_floored = max(pri_capped, pri_p50)
        else:
            pri_raw = pri_capped = None
            capped_flag = False
            pri_floored = None  # site had no peer months in its golden year - PRI-based targeting never applies to it

        pi_same_year = g.loc[(g["year"] == golden_year) & g["PI"].notna(), "PI"]
        if len(pi_same_year):
            pi_capped = min(float(pi_same_year.mean()), GOLDEN_CAP_PRI)
            pi_floored = max(pi_capped, pi_p50)
        else:
            pi_floored = None  # no PI-scored months in the golden year - fall back to PI_P75 at consumption time

        rows.append(dict(
            site=site, golden_available=True, golden_reason=None,
            golden_year=int(golden_year), pri_golden_raw=r4(pri_raw), pri_golden_capped=r4(pri_capped),
            pri_golden_capped_flag=capped_flag, pri_golden_floored=r4(pri_floored),
            pi_golden_floored=r4(pi_floored) if pi_floored is not None else None,
            degradation_rate_annual=_degradation_rate(tech.get(site)),
            already_at_best=bool(latest_year is not None and golden_year == latest_year),
        ))
    return pd.DataFrame(rows)


def r4(v):
    return None if v is None or (isinstance(v, float) and np.isnan(v)) else round(float(v), 4)


ZERO_RECOVERY_SIGNATURES = {"CURTAILMENT", "SNOW", "CLIPPING"}


def _site_recoverable_usd_yr(g: pd.DataFrame, pri_target_by_year, pi_target_by_year) -> float:
    """One site's annual recoverable$, given a per-YEAR PRI/PI target
    (a dict; P50/P75 pass the same scalar for every year, GOLDEN passes the
    degradation-adjusted series) - mirrors the client-side shortcut formula
    in explorer_template.html's computeSiteRecoverable exactly, including
    its per-branch (PRI vs PI) fallback behaviour, so the server-precomputed
    cockpit figures and the browser-recomputed explorer figures agree."""
    total_usd, n_years = 0.0, max(g["year"].nunique(), 1)
    for row in g.itertuples():
        e_act = row.E_act_mwh
        if pd.isna(e_act):
            continue
        target = None
        if row.benchmark_mode == "peer" and pd.notna(row.PRI) and row.PRI > 0:
            t = pri_target_by_year.get(row.year)
            if t is not None:
                target = e_act * t / row.PRI
        elif row.benchmark_mode == "physical" and pd.notna(row.PI) and row.PI > 0:
            t = pi_target_by_year.get(row.year)
            if t is not None:
                target = e_act * t / row.PI
        if target is None:
            continue
        gap = max(target - e_act, 0.0)
        recovered = gap * (row.rec_pct or 0.0)
        usd = 0.0 if row.signature_final in ZERO_RECOVERY_SIGNATURES else recovered * config.PPA_USD_PER_MWH
        total_usd += usd
    return total_usd / n_years


def compute_recoverable_by_benchmark(df: pd.DataFrame, golden: pd.DataFrame, pct: dict) -> pd.DataFrame:
    """Per-site annual recoverable$ under each of the three settings,
    computed server-side (not left to a live client recompute) because the
    cockpit's account rollups need every one of an account's sites summed
    together, and only some of those sites carry the month-level detail
    the cockpit's own payload embeds (Pass 3 restricted that to in-scope
    accounts to protect the payload budget) - a client-side recompute
    there would silently understate multi-site accounts with sites outside
    that cached subset. Explorer, which has every site's full monthly
    detail, still recomputes live in the browser; this is the same
    arithmetic, just run once here for the sites/screens that need a
    precomputed answer instead."""
    golden_idx = golden.set_index("site")
    rows = []
    for site, g in df.groupby("site", sort=False):
        gy = golden_idx.loc[site] if site in golden_idx.index else None
        pri_flat = {yr: pct["pri_p50"] for yr in g["year"].unique()}
        pi_flat = {yr: pct["pi_p50"] for yr in g["year"].unique()}
        usd_p50 = _site_recoverable_usd_yr(g, pri_flat, pi_flat)
        pri_flat75 = {yr: pct["pri_p75"] for yr in g["year"].unique()}
        pi_flat75 = {yr: pct["pi_p75"] for yr in g["year"].unique()}
        usd_p75 = _site_recoverable_usd_yr(g, pri_flat75, pi_flat75)

        if gy is None or not bool(gy["golden_available"]):
            usd_golden = usd_p75
        else:
            gyear, d = gy["golden_year"], gy["degradation_rate_annual"] or 0.0
            pri_base = gy["pri_golden_floored"]
            pi_base = gy["pi_golden_floored"]
            pri_series = ({yr: (pri_base * (1 - d) ** (yr - gyear)) for yr in g["year"].unique()}
                          if pd.notna(pri_base) else pri_flat75)
            pi_series = ({yr: (pi_base * (1 - d) ** (yr - gyear)) for yr in g["year"].unique()}
                         if pd.notna(pi_base) else pi_flat75)
            usd_golden = _site_recoverable_usd_yr(g, pri_series, pi_series)

        rows.append(dict(site=site, recoverable_usd_yr_p50=r4(usd_p50), recoverable_usd_yr_p75=r4(usd_p75),
                          recoverable_usd_yr_golden=r4(usd_golden)))
    return pd.DataFrame(rows)


def main():
    df = pd.read_parquet(MONTHLY_SRC)
    sites = pd.read_parquet(SITES_SRC, columns=["site", "tech_class"])

    pct = compute_percentiles(df)
    log.info("percentiles: PRI_P50=%.4f PRI_P75=%.4f PI_P50=%.4f PI_P75=%.4f",
             pct["pri_p50"], pct["pri_p75"], pct["pi_p50"], pct["pi_p75"])

    capacity_suspect = compute_capacity_suspect(df)
    n_suspect = int(capacity_suspect.sum())
    log.info("capacity_suspect: %d/%d sites flagged (trailing 12mo median PI > %.2f)",
             n_suspect, len(capacity_suspect), CAPACITY_SUSPECT_PI_THRESHOLD)

    golden = compute_golden_year(df, sites, capacity_suspect, pct["pri_p50"], pct["pi_p50"])
    golden = golden.merge(capacity_suspect.rename("capacity_suspect"), left_on="site", right_index=True, how="left")
    n_available = int(golden["golden_available"].sum())
    n_capped = int(golden["pri_golden_capped_flag"].sum())
    n_already_best = int(golden["already_at_best"].sum())
    log.info("golden year: %d/%d sites have one available, %d capped at %.2f, %d already at their best year",
             n_available, len(golden), n_capped, GOLDEN_CAP_PRI, n_already_best)

    golden.to_parquet("data/recovery_benchmark.parquet", index=False)

    import json
    with open("data/recovery_benchmark_meta.json", "w") as f:
        json.dump(dict(percentiles=pct, capacity_suspect_pi_threshold=CAPACITY_SUSPECT_PI_THRESHOLD,
                        golden_min_months_in_year=GOLDEN_MIN_MONTHS_IN_YEAR,
                        golden_min_years_history=GOLDEN_MIN_YEARS_HISTORY, golden_cap_pri=GOLDEN_CAP_PRI), f, indent=2)
    log.info("wrote data/recovery_benchmark.parquet (%d sites) and data/recovery_benchmark_meta.json", len(golden))

    # Guard checks (test 88's own conditions) run inline so a regression
    # here fails the pipeline run, not just a later test suite.
    bad = golden[golden["capacity_suspect"] & golden["golden_available"]]
    assert len(bad) == 0, f"{len(bad)} capacity_suspect site(s) still produced a golden-year figure"
    bad2 = golden[golden["golden_available"] & (golden["pri_golden_capped"] > GOLDEN_CAP_PRI + 1e-9)]
    assert len(bad2) == 0, "a golden PRI above the 1.20 cap leaked through uncapped"
    log.info("test 88 (golden guards, inline) passed")

    # §1.4/RB-8: per-site recoverable$ under all three settings, server-
    # precomputed for the cockpit's account rollups (see
    # compute_recoverable_by_benchmark's own docstring for why this can't
    # just be a live client recompute there, unlike explorer).
    by_bench = compute_recoverable_by_benchmark(df, golden, pct)
    by_bench.to_parquet("data/site_recoverable_by_benchmark.parquet", index=False)
    log.info("wrote data/site_recoverable_by_benchmark.parquet (%d sites)", len(by_bench))


if __name__ == "__main__":
    main()
