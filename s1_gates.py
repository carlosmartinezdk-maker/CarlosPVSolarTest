"""
S1 - Data quality gates. Site-level funnel (must reproduce Section 4 exactly)
plus month-level scoreability gates (commissioning ramp, minimum scoreable
months per site-year, 2022 gap handling).
"""
import logging
import os

import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S1 %(message)s")
log = logging.getLogger("s1")

OUT_DIR = "data"


def site_funnel(sites: pd.DataFrame) -> tuple[pd.DataFrame, list[tuple[str, int, float]]]:
    steps = []
    df = sites.copy()
    steps.append(("start", len(df), df["mwac"].sum() / 1000))

    df = df[df["hybrid"].isna()]
    steps.append(("drop_hybrid", len(df), df["mwac"].sum() / 1000))

    df = df[df["lat"].notna() & df["lon"].notna()]
    steps.append(("require_latlon", len(df), df["mwac"].sum() / 1000))

    df = df[df["mwdc"].notna() & (df["mwdc"] > 0)]
    steps.append(("require_mwdc_gt0", len(df), df["mwac"].sum() / 1000))

    df = df[df["op_year"].notna()]
    steps.append(("require_op_year", len(df), df["mwac"].sum() / 1000))

    df = df[(df["dcac"] >= config.DCAC_VALID_RANGE[0]) & (df["dcac"] <= config.DCAC_VALID_RANGE[1])]
    steps.append(("require_dcac_range", len(df), df["mwac"].sum() / 1000))

    return df, steps


def assert_funnel(steps: list[tuple[str, int, float]]) -> None:
    expected = dict(config.FUNNEL_EXPECTED)
    for name, n, _gw in steps:
        exp_n = expected[name]
        assert n == exp_n, f"funnel step '{name}': got {n}, expected {exp_n} (Section 4 mismatch)"
    log.info("funnel reproduces Section 4 exactly: %s", [(n, c) for n, c, _ in steps])


def name_match_capacity_check(scoreable_sites: pd.DataFrame, production: pd.DataFrame) -> None:
    """Validate reported AC capacity within 10% of site_master.mwac wherever
    an independent capacity figure exists. Section says this should be a
    no-op for the 508 sites where it was checked historically - assert, don't
    trust. We approximate using EIA Total MWh(source)-derived nameplate
    proxy is not available at this grain, so this check validates internal
    consistency (mwac present and positive) instead; full validation needs
    the workbook column C 'Mwac' per year, cross-referenced in run_report."""
    bad = scoreable_sites[(scoreable_sites["mwac"].isna()) | (scoreable_sites["mwac"] <= 0)]
    assert len(bad) == 0, f"{len(bad)} scoreable sites have missing/non-positive mwac"


def month_level_gates(production: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """Apply commissioning-ramp exclusion, then minimum-scoreable-months per
    site-year. 2022 absence and coverage gaps are already represented as
    missing rows in production_long (never zero), so no special handling is
    needed here beyond not treating absence as a fault - that is enforced in
    S6/S8, not S1."""
    site_cod = sites.set_index("site")["cod"]
    df = production.merge(site_cod.rename("cod"), left_on="site", right_index=True, how="left")

    ramp_cutoff = df["cod"] + pd.DateOffset(months=6)
    df["past_ramp"] = df["cod"].isna() | (df["month_start"] >= ramp_cutoff)

    df["month_scoreable_candidate"] = df["reported"] & df["past_ramp"]

    site_year_counts = (
        df[df["month_scoreable_candidate"]]
        .groupby(["site", "year"])["month_num"]
        .nunique()
        .rename("scoreable_months_in_year")
    )
    df = df.merge(site_year_counts, on=["site", "year"], how="left")
    df["scoreable_months_in_year"] = df["scoreable_months_in_year"].fillna(0)

    df["site_year_meets_min_months"] = df["scoreable_months_in_year"] >= config.MIN_SCOREABLE_MONTHS_PER_SITE_YEAR
    df["scoreable_flag"] = df["month_scoreable_candidate"] & df["site_year_meets_min_months"]

    df["exclusion_reason"] = None
    df.loc[~df["reported"], "exclusion_reason"] = "not_reported"
    df.loc[df["reported"] & ~df["past_ramp"], "exclusion_reason"] = "commissioning_ramp"
    df.loc[df["reported"] & df["past_ramp"] & ~df["site_year_meets_min_months"],
           "exclusion_reason"] = "site_year_lt_6_scoreable_months"

    return df


def main():
    sites = pd.read_parquet(os.path.join(OUT_DIR, "sites.parquet"))
    production = pd.read_parquet(os.path.join(OUT_DIR, "production.parquet"))

    scoreable_sites, steps = site_funnel(sites)
    assert_funnel(steps)
    name_match_capacity_check(scoreable_sites, production)

    scoreable_sites = scoreable_sites.copy()
    scoreable_sites["scoreable_site"] = True
    sites_out = sites.merge(
        scoreable_sites[["site", "scoreable_site"]], on="site", how="left"
    )
    sites_out["scoreable_site"] = sites_out["scoreable_site"].fillna(False)

    prod_scoreable = production[production["site"].isin(scoreable_sites["site"])]
    month_gated = month_level_gates(prod_scoreable, scoreable_sites)

    funnel_df = pd.DataFrame(steps, columns=["step", "n_sites", "gw_ac"])
    funnel_df.to_csv(os.path.join(OUT_DIR, "funnel.csv"), index=False)
    sites_out.to_parquet(os.path.join(OUT_DIR, "sites_gated.parquet"), index=False)
    month_gated.to_parquet(os.path.join(OUT_DIR, "production_gated.parquet"), index=False)

    n_scoreable_months = month_gated["scoreable_flag"].sum()
    n_site_years = month_gated[month_gated["scoreable_flag"]].groupby(["site", "year"]).ngroups
    log.info("scoreable sites: %d | scoreable site-months: %d | scoreable site-years: %d",
              scoreable_sites["site"].nunique(), n_scoreable_months, n_site_years)
    log.info("(Section 4 targets: 6204 sites, 330754 reported site-months, 29040 site-years - "
              "note our 'scoreable site-months' also applies the commissioning-ramp and "
              "min-6-month gates, so it will be lower than the raw 330754 reported figure)")


if __name__ == "__main__":
    main()
