"""
Stratified ~100-site subsample for pipeline validation, per the brief's own
BUILD ORDER (Section 12): "Get S0-S5 and S7 running on a stratified 100-site
subsample first... Then run S6 on the subsample and check tests 15-23...
Then scale up."

Stratify on tracking type, module technology, and years_present so the
subsample exercises every code path (peer matching across tracking types,
phased builds, short vs long history, etc).
"""
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s SUBSAMPLE %(message)s")
log = logging.getLogger("subsample")

TARGET_N = 100


def build_subsample(sites_gated: pd.DataFrame, seed: int = config.RANDOM_SEED) -> pd.DataFrame:
    df = sites_gated[sites_gated["scoreable_site"]].copy()
    rng = np.random.default_rng(seed)

    df["years_bucket"] = pd.cut(df["years_present"], bins=[0, 1, 3, 5, 8],
                                  labels=["1-2", "3", "4-5", "6-8"])
    df["strata"] = (df["tracking"].fillna("Unknown").astype(str) + "|" +
                     df["tech_class"].fillna("unknown").astype(str) + "|" +
                     df["years_bucket"].astype(str))

    n_strata = df["strata"].nunique()
    per_stratum = max(1, TARGET_N // n_strata)

    picked = []
    for _, grp in df.groupby("strata"):
        take = min(len(grp), per_stratum)
        picked.append(grp.sample(n=take, random_state=int(rng.integers(0, 1_000_000))))
    sub = pd.concat(picked)

    # top up / trim to close to TARGET_N
    if len(sub) < TARGET_N:
        remaining = df[~df["site"].isin(sub["site"])]
        extra = remaining.sample(n=min(TARGET_N - len(sub), len(remaining)),
                                  random_state=seed)
        sub = pd.concat([sub, extra])
    elif len(sub) > TARGET_N:
        sub = sub.sample(n=TARGET_N, random_state=seed)

    # Force-include: at least a couple of phased-build sites and at least one
    # site with a 2021/2023-but-not-2022 gap, so those code paths are hit.
    phased = df[df["is_phased_build"] & ~df["site"].isin(sub["site"])]
    if len(phased):
        sub = pd.concat([sub, phased.sample(n=min(3, len(phased)), random_state=seed)])

    sub = sub.drop_duplicates(subset="site")
    log.info("subsample: %d sites across %d strata (tracking x tech x years_bucket)",
              len(sub), n_strata)
    return sub


def main():
    sites_gated = pd.read_parquet("data/sites_gated.parquet")
    sub = build_subsample(sites_gated)
    sub.to_parquet("data/subsample_sites.parquet", index=False)
    log.info("tracking mix: %s", sub["tracking"].value_counts().to_dict())
    log.info("tech mix: %s", sub["tech_class"].value_counts().to_dict())
    log.info("years_present mix: %s", sub["years_present"].value_counts().sort_index().to_dict())


if __name__ == "__main__":
    main()
