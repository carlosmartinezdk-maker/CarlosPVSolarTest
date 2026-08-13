"""
S15 - Case study A: inverter/block spares planning (Reliability
Engineering Addendum, Section 7). Direct analogue of the chapter's
gearbox-spares example: given a portfolio's at-risk block population and
its fitted 24-month block-outage/full-outage probability, how many spare
blocks should the owner hold for 95% coverage?

Owner = pricing.yaml's owner_grouping_key (utility). "Spares held" is an
input we do not have real data for - this run assumes 0 (a lower-bound
"what if they're starting from nothing" framing) and reports the gap at
each of a few plausible held-counts so the owner can see where they'd
land, rather than presenting a single number as if we knew their
inventory.

CAVEAT (not in the addendum's worked example, worth stating plainly):
Section 7's own formula, `expected_failures = sum(Q_i * N_blocks_i)`,
treats each of a site's N_blocks as an independent unit each carrying the
SITE's marginal 24-month failure probability. That is a reasonable
approximation for small sites but inflates fast for very large ones (a
250-block utility-scale site with a 20% site-level probability reads as
~50 expected block failures, i.e. one failure in five blocks within two
years) - it is an upper-bound working-capital number for portfolio
planning, not a claim that a fifth of any one plant's inverters will
actually fail. Followed as specified because it is the addendum's
prescribed method, not silently adjusted.
"""
import logging

import numpy as np
import pandas as pd
from scipy import stats

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S15 %(message)s")
log = logging.getLogger("s15")

SPARES_SIGNATURES = ["BLOCK_OUTAGE", "OUTAGE_FULL"]
ASSUMED_SPARES_HELD_SCENARIOS = [0, 1, 2, 5]


def spares_for_coverage(mean_failures: float, service_level: float) -> int:
    """Smallest k such that Poisson(mean).cdf(k) >= service_level."""
    if mean_failures <= 0:
        return 0
    k = 0
    while stats.poisson.cdf(k, mean_failures) < service_level:
        k += 1
        if k > 10_000:  # pathological guard, never expected to trip
            break
    return k


def main():
    forecast = pd.read_parquet("data/reliability_forecast.parquet")
    sites = pd.read_parquet("data/subsample_sites.parquet")[["site", "utility", "mwdc"]]

    f24 = forecast[(forecast["horizon_months"] == 24) & (forecast["signature"].isin(SPARES_SIGNATURES))]
    f24 = f24.merge(sites, on="site", how="left")

    per_site = f24.groupby(["site", "utility"], as_index=False).agg(
        n_blocks=("n_blocks", "first"),
        expected_block_failures_24mo=("expected_failures_block_level", "sum"),
    )

    rows = []
    for owner, g in per_site.groupby("utility"):
        blocks_at_risk = int(g["n_blocks"].sum())
        expected = float(g["expected_block_failures_24mo"].sum())
        k95 = spares_for_coverage(expected, config.RELIABILITY["spares_service_level"])
        row = dict(
            owner=owner, n_sites=g["site"].nunique(), blocks_at_risk=blocks_at_risk,
            expected_block_failures_24mo=round(expected, 3),
            spares_needed_95pct=k95,
        )
        for held in ASSUMED_SPARES_HELD_SCENARIOS:
            coverage = float(stats.poisson.cdf(held, expected)) if expected > 0 else 1.0
            row[f"coverage_pct_if_{held}_held"] = round(100 * coverage, 1)
        rows.append(row)

    out = pd.DataFrame(rows).sort_values("expected_block_failures_24mo", ascending=False)
    out.to_parquet("data/spares_plan.parquet", index=False)

    top = out.iloc[0] if len(out) else None
    log.info("spares plan: %d owners -> data/spares_plan.parquet", len(out))
    if top is not None:
        log.info("largest exposure: %s (%d sites, ~%d blocks at risk) expects %.1f block failures in 24mo, "
                  "needs %d spares for 95%% coverage (0 held today = %.0f%% coverage)",
                  top["owner"], top["n_sites"], top["blocks_at_risk"], top["expected_block_failures_24mo"],
                  top["spares_needed_95pct"], top["coverage_pct_if_0_held"])
    log.info("S15 complete")


if __name__ == "__main__":
    main()
