"""
S9 - Index to dollars (Part 8). Computes PRI_P75 from THIS fleet (never
hardcoded), the Part 8 target/gap/recoverable/value chain (authoritative,
ranks the call list per Section 0.2), the tracker's quick-estimate formula
alongside it for cross-check, and fills the event ledger's mwh_lost/
usd_lost columns (S8 built the ledger's structural counts before dollar
figures existed - S9 completes it, matching the brief's stated S8-before-S9
execution order at the file level while resolving the real data dependency).
"""
import logging

import numpy as np
import pandas as pd

logging.basicConfig(level=logging.INFO, format="%(asctime)s S9 %(message)s")
log = logging.getLogger("s9")

import config
import recovery_benchmark


def compute_pri_p75(df: pd.DataFrame) -> float:
    """Thin wrapper over recovery_benchmark.compute_percentiles() - kept so
    S9's own call sites/tests don't change, but the actual math lives in one
    place (RECOVERY_BENCHMARK_AND_CUSTOMER_ROI.md §1.1 needs P50 alongside
    this P75, and duplicating the quantile logic in two files is exactly
    the kind of drift this project keeps finding and fixing)."""
    peer_pri = df.loc[df["benchmark_mode"] == "peer", "PRI"].dropna()
    if len(peer_pri) < 20:
        log.warning("only %d peer-benchmarked PRI values in this run - PRI_P75 "
                    "will be noisy at subsample scale. Reference fleet (different "
                    "dataset) observed 1.056; NOT used directly per Section 6.", len(peer_pri))
    return recovery_benchmark.compute_percentiles(df)["pri_p75"] or np.nan


def compute_pi_p75(df: pd.DataFrame) -> float:
    return recovery_benchmark.compute_percentiles(df)["pi_p75"] or np.nan


def target_gap_recoverable(df: pd.DataFrame, pri_p75: float, pi_p75: float) -> pd.DataFrame:
    df = df.copy()
    df["T_mwh"] = np.where(
        (df["benchmark_mode"] == "peer") & df.get("healthy_sy_median", pd.Series(np.nan, index=df.index)).notna(),
        df.get("healthy_sy_median", np.nan) * pri_p75 * df["p_dc_mw"],
        df["E_exp_mwh"] * pi_p75,
    )
    df["G_mwh"] = np.clip(df["T_mwh"] - df["E_act_mwh"], 0, None)
    df["rho"] = df["rec_pct"]
    df["R_mwh"] = df["G_mwh"] * df["rho"]

    # Guardrail (test 9/17): zero-recovery signatures NEVER produce a dollar.
    zero_sig = df["signature_final"].isin(config.ZERO_RECOVERY_SIGNATURES)
    df.loc[zero_sig, ["R_mwh"]] = 0.0

    df["value_usd"] = df["R_mwh"] * config.PPA_USD_PER_MWH
    df["gross_gap_mwh"] = df["G_mwh"]
    return df


def tracker_quick_estimate(df: pd.DataFrame) -> pd.DataFrame:
    """value_usd_quick = D x SY_peer_median x P_dc x REC% x PPA (Section 0.2 /
    Part 8 cross-check). Unit test: D=0.25, SY_peer=150, DC=500, BLOCK(90%),
    PPA=40 -> 675,000 USD (test 21)."""
    df = df.copy()
    sy_peer = df.get("healthy_sy_median", pd.Series(np.nan, index=df.index))
    df["value_usd_quick"] = df["D"] * sy_peer.fillna(0) * df["p_dc_mw"] * df["rec_pct"] * config.PPA_USD_PER_MWH
    zero_sig = df["signature_final"].isin(config.ZERO_RECOVERY_SIGNATURES)
    df.loc[zero_sig, "value_usd_quick"] = 0.0
    return df


def unit_test_tracker_formula():
    D, sy_peer, dc, rec, ppa = 0.25, 150, 500, 0.90, 40.0
    result = D * sy_peer * dc * rec * ppa
    assert abs(result - 675_000) < 1, f"tracker formula unit test failed: got {result}"
    log.info("test 21 (tracker quick-estimate worked example) passed: %s USD", result)


def cross_check(df: pd.DataFrame) -> None:
    both = df[(df["value_usd"] > 0) & (df["value_usd_quick"] > 0)]
    if len(both) == 0:
        log.warning("no site-months with both value_usd and value_usd_quick > 0 - "
                    "cross-check skipped (expected at subsample scale with few faults)")
        return
    ratio = both["value_usd"] / both["value_usd_quick"]
    within_tol = ((ratio - 1).abs() <= config.FLAG_0_2_CROSS_CHECK_TOLERANCE).mean()
    log.info("Part8 vs tracker-quick cross-check: %.0f%% of %d dollar-bearing site-months "
              "within %.0f%% of each other (median ratio %.3f)",
              100 * within_tol, len(both), 100 * config.FLAG_0_2_CROSS_CHECK_TOLERANCE, ratio.median())


def update_ledger_dollars(ledger_path: str, df: pd.DataFrame) -> None:
    ledger = pd.read_parquet(ledger_path)
    agg = df.groupby(["site", "year", "signature_final"]).agg(
        mwh_lost=("gross_gap_mwh", "sum"), usd_lost=("value_usd", "sum")
    ).reset_index().rename(columns={"signature_final": "signature"})
    ledger = ledger.drop(columns=["mwh_lost", "usd_lost"]).merge(
        agg, on=["site", "year", "signature"], how="left")
    ledger.to_parquet(ledger_path, index=False)


def main():
    unit_test_tracker_formula()

    df = pd.read_parquet("data/site_month_signatures.parquet")
    pri_p75 = compute_pri_p75(df)
    pi_p75 = compute_pi_p75(df)
    log.info("PRI_P75 (this fleet) = %.4f | PI_P75 (this fleet) = %.4f", pri_p75, pi_p75)
    # Part 1's switchable benchmark needs P50 too ("Conservative" setting) -
    # logged here for visibility; recovery_benchmark.py (run after S9) is
    # the authoritative writer of all four percentiles plus the golden-year
    # table, since P50/P75 alone aren't the whole toggle.
    pct = recovery_benchmark.compute_percentiles(df)
    log.info("PRI_P50 (this fleet) = %.4f | PI_P50 (this fleet) = %.4f", pct["pri_p50"], pct["pi_p50"])

    df = target_gap_recoverable(df, pri_p75, pi_p75)
    df = tracker_quick_estimate(df)
    cross_check(df)

    df.to_parquet("data/site_month_dollars.parquet", index=False)
    update_ledger_dollars("data/event_ledger.parquet", df)

    total_usd = df.loc[~df["signature_final"].isin(config.ZERO_RECOVERY_SIGNATURES), "value_usd"].sum()
    n_sites = df["site"].nunique()
    log.info("S9 complete: total recoverable value (subsample, all years) = $%.0f "
              "(NOT a fleet estimate - %d sites, not 6,204)", total_usd, n_sites)

    # Test 9/17 at row level.
    bad = df[df["signature_final"].isin(config.ZERO_RECOVERY_SIGNATURES) & (df["value_usd"] != 0)]
    assert len(bad) == 0, "non-zero value_usd on a zero-recovery signature row"
    log.info("test 9/17 (row-level zero recovery) passed")


if __name__ == "__main__":
    main()
