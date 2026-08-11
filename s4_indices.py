"""
S4 - Indices: PI, PR_T, SY, peer sets (BallTree/haversine), PRI.

NOTE ON PEER AVAILABILITY AT SUBSAMPLE SCALE: peer search below only
considers sites for which we have computed SY this run (i.e. sites in the
active subsample). At ~100 sites the peer minimum (4) will often not be
met, which is expected and exercises the documented fallback (PI alone,
benchmark_mode="physical", Section 0.1) rather than being a bug. At full
6,204-site scale, peer availability matches the brief's Section 4 fleet
composition and this code path does not change.
"""
import logging

import numpy as np
import pandas as pd
from sklearn.neighbors import BallTree

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S4 %(message)s")
log = logging.getLogger("s4")

EARTH_RADIUS_KM = 6371.0088


def compute_pi_prt_sy(expected: pd.DataFrame, production: pd.DataFrame,
                       sites: pd.DataFrame) -> pd.DataFrame:
    prod = production[production["reported"]][
        ["site", "year", "month_num", "month_start", "mwh", "scoreable_flag", "scoreable_months_in_year"]
    ].rename(columns={"mwh": "E_act_mwh"})

    df = expected.merge(prod, on=["site", "month_start", "year"], how="left")
    # E_act is null when the month was not reported. Never impute a zero.
    df["PI"] = np.where(df["E_act_mwh"].notna() & (df["E_exp_mwh"] > 0),
                         df["E_act_mwh"] / df["E_exp_mwh"], np.nan)
    df["PR_T"] = np.where(
        df["E_act_mwh"].notna() & (df["p_dc_mw"] > 0) & (df["pr_t_denom"] > 0),
        df["E_act_mwh"] / (df["p_dc_mw"] * df["pr_t_denom"]), np.nan)
    df["SY"] = np.where(df["E_act_mwh"].notna() & (df["p_dc_mw"] > 0),
                         df["E_act_mwh"] / df["p_dc_mw"], np.nan)

    cod = sites.set_index("site")["cod"]
    df = df.merge(cod.rename("cod"), left_on="site", right_index=True, how="left")
    df["tau_years"] = (df["month_start"] - df["cod"]).dt.days / 365.25
    df["past_ramp"] = df["cod"].isna() | (df["tau_years"] >= config.COMMISSIONING_RAMP_EXCLUSION_YEARS)
    df["no_irradiance_year"] = df["year"] == 2026  # test 27: PI/PR_T null every 2026 month

    # Section 0.7 peer-health carry-forward: 2026 rows screen on the site's
    # own 2025 mean PI instead of that month's (nonexistent) PI.
    pi_2025_mean = (df.loc[df["year"] == config.PEER_HEALTH_2026_CARRY_FORWARD_YEAR]
                     .groupby("site")["PI"].mean().rename("pi_2025_mean_carried"))
    df = df.merge(pi_2025_mean, on="site", how="left")
    df["PI_health_screen"] = np.where(df["year"] == 2026, df["pi_2025_mean_carried"], df["PI"])
    df["peer_health_carried_forward"] = (df["year"] == 2026) & df["pi_2025_mean_carried"].notna()

    return df


def build_peer_sets(month_df: pd.DataFrame, sites: pd.DataFrame) -> dict:
    """For one calendar month's cross-section, return {site: peer_info}.

    Section 0.7: 2026 has no PI (no NSRDB irradiance), so the peer health
    filter (normally PI(j,m) >= 0.85) has nothing to screen on. Fall back to
    each peer's own 2025 mean PI, carried forward - never skip the filter
    outright (an unscreened peer median is exactly the failure mode that
    produced a PRI of 2.23 in testing)."""
    meta = sites.set_index("site")[["lat", "lon", "tracking", "dcac"]]
    m = month_df.merge(meta, on="site", how="left", suffixes=("", "_m"))
    m = m[m["SY"].notna() & m["lat"].notna() & m["lon"].notna() & m["past_ramp"]].copy()
    if len(m) < 2:
        return {}
    health_pi_col = "PI_health_screen" if "PI_health_screen" in m.columns else "PI"

    coords_rad = np.radians(m[["lat", "lon"]].values)
    tree = BallTree(coords_rad, metric="haversine")

    result = {}
    for idx, row in m.iterrows():
        for radius_km in config.ADAPTIVE_RADIUS_LADDER_KM:
            radius_rad = radius_km / EARTH_RADIUS_KM
            ind = tree.query_radius(coords_rad[m.index.get_loc(idx)].reshape(1, -1),
                                     r=radius_rad)[0]
            cand = m.iloc[ind]
            cand = cand[cand["site"] != row["site"]]
            cand = cand[cand["tracking"] == row["tracking"]]
            cand = cand[(cand["tau_years"] - row["tau_years"]).abs() <= config.PEER_AGE_WINDOW_YEARS]
            cand = cand[(cand["dcac"] - row["dcac"]).abs() <= config.PEER_DCAC_WINDOW]
            if len(cand) >= config.PEER_SET_TARGET or radius_km == config.ADAPTIVE_RADIUS_LADDER_KM[-1]:
                break
        healthy = cand[cand[health_pi_col] >= config.PEER_HEALTH_FLOOR_PI]
        result[row["site"]] = dict(
            peer_count=len(cand), peer_radius_km=radius_km,
            peers_healthy=len(healthy),
            healthy_sy_median=healthy["SY"].median() if len(healthy) else np.nan,
        )
    return result


def compute_pri(df: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    out_rows = []
    for month_start, month_df in df.groupby("month_start"):
        peers = build_peer_sets(month_df, sites)
        for _, row in month_df.iterrows():
            info = peers.get(row["site"])
            r = row.to_dict()
            if info is None or info["peers_healthy"] < config.PEER_MINIMUM:
                r.update(peer_count=info["peer_count"] if info else 0,
                         peer_radius_km=info["peer_radius_km"] if info else np.nan,
                         peers_healthy=info["peers_healthy"] if info else 0,
                         PRI=np.nan, benchmark_mode="physical",
                         healthy_sy_median=info["healthy_sy_median"] if info else np.nan)
            else:
                pri = row["SY"] / info["healthy_sy_median"] if pd.notna(row["SY"]) and info["healthy_sy_median"] > 0 else np.nan
                r.update(peer_count=info["peer_count"], peer_radius_km=info["peer_radius_km"],
                         peers_healthy=info["peers_healthy"], PRI=pri, benchmark_mode="peer",
                         healthy_sy_median=info["healthy_sy_median"])
            out_rows.append(r)
    return pd.DataFrame(out_rows)


def score_fallback_pi_adj(df: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """Section 0.1 default: score_fallback = PI_adj = PI / median over the
    region of PI in that month, for site-months with no valid peer group."""
    region = sites.set_index("site")["state"]
    df = df.merge(region.rename("region"), left_on="site", right_index=True, how="left")
    region_month_median = (
        df[df["PI"].notna()].groupby(["region", "month_start"])["PI"].median()
        .rename("region_month_median_pi")
    )
    df = df.merge(region_month_median, on=["region", "month_start"], how="left")
    df["PI_adj"] = df["PI"] / df["region_month_median_pi"]
    return df


def assemble_score(df: pd.DataFrame) -> pd.DataFrame:
    df["score"] = np.where(df["benchmark_mode"] == "peer", df["PRI"], df["PI_adj"])
    return df


def main():
    expected = pd.read_parquet("data/expected_generation.parquet")
    production = pd.read_parquet("data/production_gated.parquet")
    sites = pd.read_parquet("data/sites_gated.parquet")

    df = compute_pi_prt_sy(expected, production, sites)
    df = compute_pri(df, sites)
    df = score_fallback_pi_adj(df, sites)
    df = assemble_score(df)

    df.to_parquet("data/site_month_indices.parquet", index=False)

    n_peer = (df["benchmark_mode"] == "peer").sum()
    n_phys = (df["benchmark_mode"] == "physical").sum()
    log.info("S4 complete: %d site-months (%d peer-benchmarked, %d physical-fallback, %.0f%% peer)",
              len(df), n_peer, n_phys, 100 * n_peer / max(1, n_peer + n_phys))
    log.info("PI describe: %s", df["PI"].describe().to_dict())
    log.info("PRI describe (peer-benchmarked only): %s",
              df.loc[df["benchmark_mode"] == "peer", "PRI"].describe().to_dict())

    # Acceptance test 7: no peer with PI < 0.85 in any peer median (structural
    # - the health filter excludes them before the median is taken).
    # Acceptance test 8: PRI is null wherever peer_count/peers_healthy < 4.
    bad8 = df[(df["benchmark_mode"] == "peer") & (df["peers_healthy"] < config.PEER_MINIMUM)]
    assert len(bad8) == 0, "benchmark_mode=peer with peers_healthy < PEER_MINIMUM"
    bad8b = df[(df["benchmark_mode"] == "physical") & df["PRI"].notna()]
    assert len(bad8b) == 0, "PRI non-null in physical-fallback rows"
    log.info("test 8 (peer minimum -> PRI null) passed")


if __name__ == "__main__":
    main()
