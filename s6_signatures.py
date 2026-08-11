"""
S6 - D-Band fault classifier (Fault Estimation Tracker). Runs AFTER S7
because DEGRADATION's discriminator needs the trajectory slope.

Simplifications documented here, not hidden: this runs on the ~100-site
subsample, so:
  - G1 (curtailment) BA-month medians are computed over whatever scoreable
    plants exist IN THE SUBSAMPLE for that BA-month, which will often be < 3
    (the gate's own minimum), so G1 will rarely fire here. At full 6,204-site
    scale every BA has many plants and this gate becomes meaningful.
  - TRACKER's daylight-hours correlation uses an analytic day-length formula
    (solar declination) rather than a measured-daylight column, since no
    such column exists in any input file.
"""
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S6 %(message)s")
log = logging.getLogger("s6")


# --------------------------------------------------------------------------
# D and gates
# --------------------------------------------------------------------------

def compute_D(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["D"] = np.clip(1 - df["score"], 0, None)
    df.loc[df["score"].isna(), "D"] = np.nan
    return df


def day_length_hours(lat_deg: float, day_of_year: np.ndarray) -> np.ndarray:
    """Analytic day length (hours) from solar declination - used as the
    TRACKER discriminator's daylight-hours proxy (no measured column
    exists in the inputs)."""
    decl = np.radians(23.44) * np.sin(2 * np.pi * (284 + day_of_year) / 365.0)
    lat = np.radians(lat_deg)
    cos_h = -np.tan(lat) * np.tan(decl)
    cos_h = np.clip(cos_h, -1, 1)
    h = np.degrees(np.arccos(cos_h))
    return 2 * h / 15.0


def ba_month_medians(df: pd.DataFrame) -> pd.Series:
    scoreable = df[df["score"].notna()]
    counts = scoreable.groupby(["ba", "month_start"])["site"].nunique()
    medians = scoreable.groupby(["ba", "month_start"])["score"].median()
    medians = medians[counts >= config.G1_MIN_PLANTS_IN_BA_MONTH]
    return medians


def apply_gates(df: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    df = df.merge(sites.set_index("site")[["ba", "lat", "dcac", "is_phased_build"]].rename(
        columns={"lat": "site_lat", "dcac": "site_dcac"}), left_on="site", right_index=True, how="left")
    # Step 5 downgrade reason: COD within 6 months of the affected month -
    # i.e. still close to the commissioning-ramp boundary even though the
    # month itself cleared the S1 ramp-exclusion gate.
    df["commissioning_adjacent"] = df["tau_years"].notna() & (df["tau_years"] < 1.0)

    medians = ba_month_medians(df)
    df = df.merge(medians.rename("ba_month_median_score"), on=["ba", "month_start"], how="left")

    df["gate_fired"] = None

    g1 = (df["ba_month_median_score"].notna() &
          (df["ba_month_median_score"] < config.G1_BA_MEDIAN_SCORE_CEILING) &
          ((df["score"] - df["ba_month_median_score"]).abs() <= config.G1_SITE_TO_BA_TOLERANCE))
    df.loc[g1, "gate_fired"] = "G1_CURTAILMENT"

    # G2 snow: needs Apr-Oct mean score of the SAME year, or prior year for
    # 2026 winter months per Section 0.6 default.
    summer = df[df["month_start"].dt.month.isin(config.G2_SUMMER_MONTHS)]
    summer_mean = summer.groupby(["site", "year"])["score"].mean().rename("summer_mean_score")
    df = df.merge(summer_mean, on=["site", "year"], how="left")

    is_2026_winter = (df["year"] == 2026) & (df["month_start"].dt.month.isin(config.G2_SNOW_MONTHS))
    # "Prior year" means the most recent FULL year before 2026 - 2026's own
    # partial Apr-May rows must never be picked as the borrowed baseline.
    summer_pre_2026 = summer[summer["year"] < 2026]
    prior_summer = summer_pre_2026.groupby(["site"]).apply(
        lambda g: g[g["year"] == g["year"].max()]["score"].mean(), include_groups=False
    ).rename("prior_year_summer_mean")
    df = df.merge(prior_summer, on="site", how="left")
    df["summer_ref_score"] = np.where(is_2026_winter, df["prior_year_summer_mean"], df["summer_mean_score"])
    df["benchmark_year_borrowed"] = is_2026_winter & df["prior_year_summer_mean"].notna()
    df["snow_gate_unevaluated"] = is_2026_winter & df["prior_year_summer_mean"].isna()

    g2 = (df["gate_fired"].isna() &
          (df["site_lat"] >= config.G2_SNOW_LATITUDE_FLOOR) &
          df["month_start"].dt.month.isin(config.G2_SNOW_MONTHS) &
          (df["summer_ref_score"] >= config.G2_SUMMER_HEALTH_FLOOR))
    df.loc[g2, "gate_fired"] = "G2_SNOW"

    g3 = (df["gate_fired"].isna() &
          (df["benchmark_mode"] == "peer") &
          (df["site_dcac"] >= config.G3_CLIPPING_DCAC_FLOOR) &
          df["month_start"].dt.month.isin(config.G3_CLIPPING_MONTHS) &
          (df["PRI"] >= config.G3_CLIPPING_PRI_FLOOR))
    df.loc[g3, "gate_fired"] = "G3_CLIPPING"

    return df


# --------------------------------------------------------------------------
# Bands / block fraction
# --------------------------------------------------------------------------

def band_D(d: float) -> str:
    if pd.isna(d):
        return "unscored"
    if d < config.D_NOISE_CEILING:
        return "NOISE"
    if d < config.D_WATCH_BAND_HIGH:
        return "WATCH"
    if d < 0.15:
        return "0.08-0.15"
    if d < 0.30:
        return "0.15-0.30"
    if d < 0.50:
        return "0.30-0.50"
    if d < config.D_OUTAGE_FLOOR:
        return "0.50-0.70"
    return "OUTAGE_FULL_BAND"


def nearest_block_fraction(d: float) -> tuple[str, int]:
    table = config.BLOCK_FRACTION_TABLE
    diffs = [(abs(d - val), val, frac) for val, frac in table]
    diffs.sort(key=lambda t: t[0])
    within_tol = [t for t in diffs if t[0] <= config.BLOCK_FRACTION_TOLERANCE]
    if not within_tol:
        return None, 0
    nearest = within_tol[0]
    return nearest[2], len(within_tol)


# --------------------------------------------------------------------------
# Runs (gap-tolerant, calendar-month based - a missing month neither breaks
# nor extends a run, per acceptance tests 2/3)
# --------------------------------------------------------------------------

def month_ordinal(ts: pd.Timestamp) -> int:
    return ts.year * 12 + ts.month


def find_runs(site_df: pd.DataFrame) -> list[pd.DataFrame]:
    faultable = site_df[(site_df["gate_fired"].isna()) & (site_df["D"] >= config.D_FAULT_FLOOR)]
    faultable = faultable.sort_values("month_start")
    if len(faultable) == 0:
        return []
    runs, current = [], [faultable.iloc[0]]
    for i in range(1, len(faultable)):
        prev_row, row = faultable.iloc[i - 1], faultable.iloc[i]
        gap = month_ordinal(row["month_start"]) - month_ordinal(prev_row["month_start"])
        if gap <= config.EPISODE_GAP_TOLERANCE_MONTHS + 1:
            current.append(row)
        else:
            runs.append(pd.DataFrame(current))
            current = [row]
    runs.append(pd.DataFrame(current))
    return runs


# --------------------------------------------------------------------------
# Discriminators (Step 4)
# --------------------------------------------------------------------------

def score_block(run: pd.DataFrame, site_df: pd.DataFrame) -> tuple[int, dict]:
    if len(run) < 2:
        return 0, {}
    flat = run["D"].std() < config.BLOCK_FLAT_STD_TOLERANCE
    first_month = run.iloc[0]["month_start"]
    prior = site_df[site_df["month_start"] < first_month].sort_values("month_start")
    step_onset = False
    if len(prior):
        prior_d = prior.iloc[-1]["D"]
        if pd.notna(prior_d):
            step_onset = (run.iloc[0]["D"] - prior_d) >= config.BLOCK_STEP_ONSET_RISE
    score = 0
    if flat:
        score += config.DISCRIMINATOR_SCORES["BLOCK_flat_fraction"]
    if step_onset:
        score += config.DISCRIMINATOR_SCORES["BLOCK_step_onset"]
    return score, dict(flat=flat, step_onset=step_onset)


def score_soiling(run: pd.DataFrame) -> tuple[int, dict]:
    if len(run) < config.SOILING_RISE_MIN_MONTHS:
        return 0, {}
    d_vals = run["D"].values
    monotonic = np.all(np.diff(d_vals[:config.SOILING_RISE_MIN_MONTHS]) >= 0)
    total_rise = d_vals[config.SOILING_RISE_MIN_MONTHS - 1] - d_vals[0]
    rise_ok = monotonic and total_rise >= config.SOILING_RISE_MIN_TOTAL
    score = 0
    reset_drop = False
    if rise_ok:
        score += config.DISCRIMINATOR_SCORES["SOILING_monotonic_rise"]
        if len(d_vals) > config.SOILING_RISE_MIN_MONTHS:
            drop = d_vals[config.SOILING_RISE_MIN_MONTHS - 1] - d_vals[config.SOILING_RISE_MIN_MONTHS]
            reset_drop = drop >= config.SOILING_RESET_DROP_MIN
            if reset_drop:
                score += config.DISCRIMINATOR_SCORES["SOILING_reset_drop"]
    return score, dict(rise_ok=rise_ok, reset_drop=reset_drop)


def score_tracker_year(year_df: pd.DataFrame, lat: float, tracking: str) -> tuple[int, dict]:
    g = year_df[year_df["D"].notna()]
    if len(g) < 3:
        return 0, {}
    doy = g["month_start"].dt.dayofyear.values
    daylight = day_length_hours(lat, doy)
    if np.std(daylight) == 0 or np.std(g["D"]) == 0:
        corr = 0.0
    else:
        corr = np.corrcoef(g["D"].values, daylight)[0, 1]
    score = 0
    if corr >= config.TRACKER_DAYLIGHT_CORR_FLOOR:
        score += config.DISCRIMINATOR_SCORES["TRACKER_daylight_corr"]
    if tracking == "Single-axis":
        score += config.DISCRIMINATOR_SCORES["TRACKER_single_axis"]
    return score, dict(daylight_corr=corr)


def score_degradation_year(year_df: pd.DataFrame, beta_excess: float) -> tuple[int, dict]:
    g = year_df[year_df["D"].notna()]
    n_persist = (g["D"] >= config.DEGRADATION_PERSISTENCE_D_FLOOR).sum()
    cv = g["D"].std() / g["D"].mean() if g["D"].mean() not in (0, None) and pd.notna(g["D"].mean()) else np.nan
    persistence = n_persist >= config.DEGRADATION_PERSISTENCE_MONTHS and pd.notna(cv) and cv < config.DEGRADATION_PERSISTENCE_CV_CEILING
    yoy_decline = pd.notna(beta_excess) and beta_excess < -config.DEGRADATION_YOY_DECLINE_PCT
    score = 0
    if persistence:
        score += config.DISCRIMINATOR_SCORES["DEGRADATION_persistence"]
    if yoy_decline:
        score += config.DISCRIMINATOR_SCORES["DEGRADATION_yoy_decline"]
    return score, dict(persistence=persistence, yoy_decline=yoy_decline, cv=cv)


def score_bos_year(year_df: pd.DataFrame) -> tuple[int, dict]:
    g = year_df[year_df["D"].notna()]
    if len(g) < 3 or g["D"].mean() in (0, None) or pd.isna(g["D"].mean()):
        return 0, {}
    cv = g["D"].std() / g["D"].mean()
    dispersion = cv >= config.BOS_DISPERSION_CV_FLOOR
    spikes = g[g["D"] >= config.BOS_SPIKE_D_FLOOR].sort_values("month_start")
    nonconsec = 0
    prev = None
    for _, row in spikes.iterrows():
        if prev is None or month_ordinal(row["month_start"]) - month_ordinal(prev) > 1:
            nonconsec += 1
        prev = row["month_start"]
    score = 0
    if dispersion:
        score += config.DISCRIMINATOR_SCORES["BOS_dispersion"]
    if nonconsec >= config.BOS_SPIKE_MIN_MONTHS:
        score += config.DISCRIMINATOR_SCORES["BOS_nonconsecutive_spikes"]
    return score, dict(cv=cv, nonconsec_spikes=nonconsec)


# --------------------------------------------------------------------------
# Orchestration per site
# --------------------------------------------------------------------------

def classify_site(site_df: pd.DataFrame, site_meta: pd.Series, beta_excess: float) -> pd.DataFrame:
    site_df = site_df.sort_values("month_start").reset_index(drop=True)
    result = {ts: dict(signature_raw="NONE", winner_score=0, score_vector={}, block_fraction=None,
                        n_candidates=0, claimed_by=None)
              for ts in site_df["month_start"]}

    # Gated / watch-band / noise months resolve immediately, no attribution needed.
    for _, row in site_df.iterrows():
        ts = row["month_start"]
        if pd.notna(row["gate_fired"]):
            result[ts]["signature_raw"] = row["gate_fired"].split("_", 1)[1]
            result[ts]["claimed_by"] = "gate"
        elif pd.isna(row["D"]):
            result[ts]["signature_raw"] = "UNSCORED"
        elif row["D"] < config.D_NOISE_CEILING:
            result[ts]["signature_raw"] = "NONE"
        elif row["D"] < config.D_WATCH_BAND_HIGH:
            result[ts]["signature_raw"] = "WATCH_NOT_A_FAULT"

    # OUTAGE: single-month D >= 0.70, evaluated first (Section 0.4 order).
    for _, row in site_df.iterrows():
        ts = row["month_start"]
        if result[ts]["claimed_by"] is not None:
            continue
        if pd.notna(row["D"]) and row["D"] >= config.D_OUTAGE_FLOOR:
            result[ts].update(signature_raw="OUTAGE_FULL",
                               winner_score=config.DISCRIMINATOR_SCORES["OUTAGE_single_month"],
                               score_vector={"OUTAGE": config.DISCRIMINATOR_SCORES["OUTAGE_single_month"]},
                               claimed_by="OUTAGE_month")

    # Runs for BLOCK / SOILING (run-level, claim unclaimed months only).
    runs = find_runs(site_df)
    for run in runs:
        run = run[run["month_start"].map(lambda t: result[t]["claimed_by"] is None)]
        if len(run) == 0:
            continue
        block_score, block_info = score_block(run, site_df)
        soil_score, soil_info = score_soiling(run)
        vec = {"BLOCK": block_score, "SOILING": soil_score}
        winner = max(vec, key=vec.get)
        if vec[winner] < config.MINIMUM_WINNING_SCORE:
            continue
        for _, row in run.iterrows():
            ts = row["month_start"]
            sig = winner
            frac, n_cand = (None, 0)
            if sig == "BLOCK" and block_info.get("flat") and block_info.get("step_onset"):
                frac, n_cand = nearest_block_fraction(row["D"])
            result[ts].update(signature_raw="BLOCK_OUTAGE" if sig == "BLOCK" else "SOILING",
                               winner_score=vec[winner], score_vector=vec,
                               block_fraction=frac, n_candidates=n_cand,
                               claimed_by=f"{sig}_run")

    # Year-level winner (TRACKER / DEGRADATION / BOS) for whatever remains.
    d_by_month = site_df.set_index("month_start")["D"]
    for year, year_df in site_df.groupby("year"):
        unclaimed_mask = year_df["month_start"].map(
            lambda t: result[t]["claimed_by"] is None and pd.notna(d_by_month.get(t))
            and d_by_month.get(t) >= config.D_FAULT_FLOOR)
        unclaimed = year_df[unclaimed_mask]
        if len(unclaimed) == 0:
            continue
        tr_score, tr_info = score_tracker_year(year_df, site_meta["lat"], site_meta["tracking"])
        dg_score, dg_info = score_degradation_year(year_df, beta_excess)
        bos_score, bos_info = score_bos_year(year_df)
        vec = {"TRACKER": tr_score, "DEGRADATION": dg_score, "BOS": bos_score}
        winner = max(vec, key=vec.get)
        if vec[winner] < config.MINIMUM_WINNING_SCORE:
            sig_name = "UNATTRIBUTED"
        else:
            sig_name = {"TRACKER": "TRACKER", "DEGRADATION": "DEGRADATION", "BOS": "BOS_INTERMITTENT"}[winner]
        for _, row in unclaimed.iterrows():
            ts = row["month_start"]
            result[ts].update(signature_raw=sig_name, winner_score=vec[winner], score_vector=vec,
                               claimed_by="year_level")

    out = []
    for ts, r in result.items():
        r = dict(r)
        r["month_start"] = ts
        r["site"] = site_df["site"].iloc[0]
        out.append(r)
    return pd.DataFrame(out)


def confidence_and_relabel(df: pd.DataFrame, sites: pd.DataFrame, traj: pd.DataFrame) -> pd.DataFrame:
    years_present = sites.set_index("site")["years_present"]
    decision_grade = traj.set_index("site")["decision_grade"]

    def eval_row(row):
        sig = row["signature_raw"]
        if sig in ("NONE", "WATCH_NOT_A_FAULT", "UNSCORED", "CURTAILMENT", "SNOW", "CLIPPING"):
            return pd.Series(dict(signature_final=sig, confidence=None, downgrade_reasons=[]))

        score = row["winner_score"]
        peers_healthy = row.get("peers_healthy", 0)
        yrs = years_present.get(row["site"], 0)

        if score >= config.CONFIDENCE_HIGH_MIN_SCORE and peers_healthy >= config.CONFIDENCE_HIGH_MIN_HEALTHY_PEERS \
                and yrs >= config.CONFIDENCE_HIGH_MIN_YEARS:
            conf = "HIGH"
        elif config.CONFIDENCE_MEDIUM_MIN_SCORE <= score <= config.CONFIDENCE_MEDIUM_MAX_SCORE \
                and peers_healthy >= config.CONFIDENCE_MEDIUM_MIN_HEALTHY_PEERS:
            conf = "MEDIUM"
        else:
            conf = "LOW"

        reasons = []
        if row.get("is_phased_build", False):
            reasons.append("phased_build")
        if row.get("scoreable_months_in_year", 99) < config.MIN_SCOREABLE_MONTHS_PER_SITE_YEAR:
            reasons.append("lt_6_scored_months")
        if row.get("commissioning_adjacent", False):
            reasons.append("commissioning_ramp_adjacent")
        if row.get("benchmark_mode") == "physical":
            reasons.append("physical_benchmark")

        if reasons and conf == "HIGH":
            conf = "MEDIUM"
        elif reasons and conf == "MEDIUM":
            conf = "LOW"

        sig_final = "UNATTRIBUTED" if conf == "LOW" else sig
        return pd.Series(dict(signature_final=sig_final, confidence=conf, downgrade_reasons=reasons))

    extra = df.apply(eval_row, axis=1)
    return pd.concat([df, extra], axis=1)


def attach_action_map(df: pd.DataFrame) -> pd.DataFrame:
    action = df["signature_final"].map(lambda s: config.SIGNATURE_ACTION_MAP.get(s, config.SIGNATURE_ACTION_MAP["NONE"]))
    df["rec_pct"] = action.map(lambda a: a["rec_pct"])
    df["inspection"] = action.map(lambda a: a["inspection"])
    df["preventative"] = action.map(lambda a: a["preventative"])
    df["fault_flag"] = (df["D"].notna() & (df["D"] >= config.D_FAULT_FLOOR) &
                         ~df["signature_final"].isin(list(config.EXPOSURE_LEDGER_SIGNATURES) +
                                                       ["NONE", "WATCH_NOT_A_FAULT", "UNSCORED"]))
    return df


def main():
    df = pd.read_parquet("data/site_month_trajectory.parquet")
    sites = pd.read_parquet("data/sites_gated.parquet")
    traj = pd.read_parquet("data/site_trajectory.parquet")

    df = compute_D(df)
    df = apply_gates(df, sites)

    beta_excess_map = traj.set_index("site")["beta_excess"]

    all_results = []
    for site, site_df in df.groupby("site"):
        site_meta = sites.set_index("site").loc[site]
        be = beta_excess_map.get(site, np.nan)
        r = classify_site(site_df, site_meta, be)
        all_results.append(r)
    sig_df = pd.concat(all_results, ignore_index=True)

    df = df.merge(sig_df, on=["site", "month_start"], how="left")
    df = confidence_and_relabel(df, sites, traj)
    df = attach_action_map(df)

    df.to_parquet("data/site_month_signatures.parquet", index=False)

    log.info("S6 complete: %d site-months classified", len(df))
    log.info("signature_raw counts: %s", df["signature_raw"].value_counts().to_dict())
    log.info("signature_final counts: %s", df["signature_final"].value_counts().to_dict())
    log.info("confidence counts: %s", df["confidence"].value_counts(dropna=False).to_dict())

    # Acceptance test 9/17: zero recovery signatures always rec_pct==0.
    bad9 = df[df["signature_final"].isin(config.ZERO_RECOVERY_SIGNATURES) & (df["rec_pct"] != 0.0)]
    assert len(bad9) == 0, "non-zero rec_pct on a zero-recovery signature"
    log.info("test 9/17 (zero recovery guardrail) passed")

    # Acceptance test 19: no signature_final outside {UNATTRIBUTED, zero-recovery} carries LOW confidence.
    allowed_low = set(config.ZERO_RECOVERY_SIGNATURES) | {"UNATTRIBUTED"}
    bad19 = df[(df["confidence"] == "LOW") & ~df["signature_final"].isin(allowed_low)]
    assert len(bad19) == 0, "LOW confidence on a non-UNATTRIBUTED, non-zero-recovery signature"
    log.info("test 19 (LOW -> UNATTRIBUTED relabel) passed")

    # Acceptance test 20: watch band excluded from fault_flag.
    bad20 = df[(df["D"] >= config.D_NOISE_CEILING) & (df["D"] < config.D_WATCH_BAND_HIGH) & df["fault_flag"]]
    assert len(bad20) == 0, "watch-band month counted as a fault"
    log.info("test 20 (watch band excluded) passed")


if __name__ == "__main__":
    main()
