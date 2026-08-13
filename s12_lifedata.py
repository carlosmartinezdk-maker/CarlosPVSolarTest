"""
S12 - Life data construction (Reliability Engineering Addendum, Section 2-3).

Builds repairable-system life records for the 6 reliability-eligible fault
signatures (config.RELIABILITY_SIGNATURES: OUTAGE_FULL, BLOCK_OUTAGE,
SOILING, TRACKER, BOS_INTERMITTENT, UNATTRIBUTED). CURTAILMENT/SNOW/CLIPPING
are exposure, not unreliability (same guardrail as ZERO_RECOVERY_SIGNATURES);
DEGRADATION is a continuous state already handled by S7, not a discrete
failure - both are excluded here.

Source of failure timing is data/episodes.parquet (one row per continuous
site+signature episode), NOT data/event_ledger.parquet - the ledger is a
yearly aggregate and cannot localize a failure to a month. Left truncation:
a site only enters the risk set at its first PI-scored month (entry_date),
since months before that were never observed (unscored) and any episode
starting before COD reflects a bad COD estimate, not a real pre-installation
failure - those rows are quarantined, not treated as age-zero events.

Two outputs:
  data/life_records.parquet      - one row per renewal spell (site x
                                    signature), F(ailure) or S(uspended),
                                    ready for left-truncated MLE fitting in S13
  data/recurrence_intervals.parquet - inter-arrival gaps between consecutive
                                    failures at the same site+signature,
                                    final interval right-censored
"""
import logging

import numpy as np
import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S12 %(message)s")
log = logging.getLogger("s12")


def parse_block_fraction(s):
    """'2/9' -> (2, 9). Returns None for anything unparseable/null."""
    if not isinstance(s, str) or "/" not in s:
        return None
    try:
        num, den = s.split("/")
        num, den = int(num), int(den)
        if den <= 0:
            return None
        return num, den
    except ValueError:
        return None


def compute_n_blocks(smd: pd.DataFrame, sites: pd.DataFrame) -> pd.DataFrame:
    """Per-site total block count: modal denominator among that site's
    fitted block_fraction months, falling back to mwdc/block_mw_default
    (config.RELIABILITY) rounded to the nearest integer, floored at 1."""
    denoms = smd["block_fraction"].map(parse_block_fraction).dropna()
    smd = smd.assign(_denom=[d[1] if d is not None else np.nan
                              for d in smd["block_fraction"].map(parse_block_fraction)])
    modal = (smd.dropna(subset=["_denom"])
                .groupby("site")["_denom"]
                .agg(lambda s: s.mode().iloc[0])
                .rename("n_blocks_fitted"))
    out = sites[["site", "mwdc"]].merge(modal, on="site", how="left")
    fallback = np.maximum(1, np.round(out["mwdc"] / config.RELIABILITY["block_mw_default"]))
    out["n_blocks"] = out["n_blocks_fitted"].fillna(fallback).astype(int)
    out["n_blocks_source"] = np.where(out["n_blocks_fitted"].notna(), "fitted", "mwdc_fallback")
    return out[["site", "n_blocks", "n_blocks_source"]]


def site_observation_window(smd: pd.DataFrame) -> pd.DataFrame:
    """entry_date/last_known_date = first/last PI-scored month per site -
    the left-truncation and right-censoring anchors. A site with zero
    PI-scored months contributes no life records (never entered observation)."""
    scored = smd[smd["PI"].notna()]
    win = scored.groupby("site")["month_start"].agg(entry_date="min", last_known_date="max")
    return win.reset_index()


def build_life_records(episodes: pd.DataFrame, sites: pd.DataFrame,
                        window: pd.DataFrame, n_blocks: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    ep = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)].copy()
    ep = ep.merge(sites[["site", "cod", "mwdc", "state", "utility", "tech_class"]], on="site", how="left")
    ep = ep.merge(window, on="site", how="left")
    ep = ep.merge(n_blocks, on="site", how="left")
    ep["age_start_years"] = (ep["start"] - ep["cod"]).dt.days / 365.25

    n_no_window = ep["entry_date"].isna().sum()
    if n_no_window:
        log.warning("%d episodes dropped: site has zero PI-scored months (never entered observation)", n_no_window)
    ep = ep.dropna(subset=["entry_date"])

    quarantined = ep[ep["age_start_years"] < 0]
    if len(quarantined):
        log.warning("quarantining %d/%d reliability-signature episodes with age_start < 0 "
                    "(COD estimate is later than the episode's actual start - not a real "
                    "pre-installation failure, excluded from life-data fitting)",
                    len(quarantined), len(ep))
    ep = ep[ep["age_start_years"] >= 0].copy()

    # Also drop episodes that start before the site's own entry_date - the
    # episode may be real, but it occurred before the site was observable
    # (e.g. carried-forward score from an earlier partial run); its true
    # onset time inside the unobserved window is unknown.
    n_pre_entry = (ep["start"] < ep["entry_date"]).sum()
    if n_pre_entry:
        log.warning("dropping %d episodes starting before the site's first PI-scored month "
                    "(onset inside the unobserved window is unknown)", n_pre_entry)
    ep = ep[ep["start"] >= ep["entry_date"]].copy()

    ep["age_entry_years"] = (ep["entry_date"] - ep["cod"]).dt.days / 365.25
    ep["age_last_known_years"] = (ep["last_known_date"] - ep["cod"]).dt.days / 365.25
    ep = ep.sort_values(["site", "signature", "start"])

    life_rows = []
    recur_rows = []
    key_cols = ["site", "signature", "cod", "entry_date", "age_entry_years",
                "last_known_date", "age_last_known_years", "n_blocks", "mwdc",
                "state", "utility", "tech_class"]
    for (site, sig), g in ep.groupby(["site", "signature"], sort=False):
        head = g.iloc[0]
        prev_age = head["age_entry_years"]
        prev_end_date = head["entry_date"]
        for i, row in enumerate(g.itertuples()):
            frac = parse_block_fraction(row.block_fraction) if hasattr(row, "block_fraction") else None
            n_affected = round(frac[0] / frac[1] * row.n_blocks) if frac else None
            life_rows.append({
                "site": site, "signature": sig, "equipment_key": f"{site}|{sig}",
                "cod": row.cod, "entry_date": row.entry_date, "age_entry_years": row.age_entry_years,
                "last_known_date": row.last_known_date, "age_last_known_years": row.age_last_known_years,
                "spell_index": i, "age_at_event_years": row.age_start_years,
                "duration_years": row.age_start_years - prev_age,
                "status": "F", "n_months": row.n_months, "max_D": row.max_D,
                "n_blocks": row.n_blocks, "n_affected_blocks": n_affected,
                "mwdc": row.mwdc, "state": row.state, "utility": row.utility, "tech_class": row.tech_class,
            })
            if i > 0:
                recur_rows.append({
                    "site": site, "signature": sig, "equipment_key": f"{site}|{sig}",
                    "interval_index": i, "gap_start": prev_end_date, "gap_end": row.start,
                    "gap_months": (row.start - prev_end_date).days / 30.4375,
                    "status": "F",
                })
            prev_age = row.age_start_years
            prev_end_date = row.end
        # final spell/interval: right-censored at last_known_date
        tail_age = head["age_last_known_years"]
        if tail_age > prev_age:
            life_rows.append({
                "site": site, "signature": sig, "equipment_key": f"{site}|{sig}",
                "cod": head["cod"], "entry_date": head["entry_date"], "age_entry_years": head["age_entry_years"],
                "last_known_date": head["last_known_date"], "age_last_known_years": head["age_last_known_years"],
                "spell_index": len(g), "age_at_event_years": tail_age,
                "duration_years": tail_age - prev_age,
                "status": "S", "n_months": None, "max_D": None,
                "n_blocks": head["n_blocks"], "n_affected_blocks": None,
                "mwdc": head["mwdc"], "state": head["state"], "utility": head["utility"],
                "tech_class": head["tech_class"],
            })
            recur_rows.append({
                "site": site, "signature": sig, "equipment_key": f"{site}|{sig}",
                "interval_index": len(g), "gap_start": prev_end_date, "gap_end": head["last_known_date"],
                "gap_months": (head["last_known_date"] - prev_end_date).days / 30.4375,
                "status": "S",
            })

    life = pd.DataFrame(life_rows)
    recur = pd.DataFrame(recur_rows)
    return life, recur


def add_never_failed_sites(life: pd.DataFrame, sites: pd.DataFrame, window: pd.DataFrame,
                            n_blocks: pd.DataFrame) -> pd.DataFrame:
    """Sites entered into observation but with zero episodes for a given
    signature never appear in `episodes` at all - without this they'd be
    silently missing from the risk set instead of contributing a fully
    right-censored spell, which would bias fitted failure rates upward."""
    have = set(zip(life["site"], life["signature"]))
    base = sites[["site", "cod", "state", "utility", "tech_class", "mwdc"]].merge(window, on="site", how="inner").merge(n_blocks, on="site", how="left")
    base["age_entry_years"] = (base["entry_date"] - base["cod"]).dt.days / 365.25
    base["age_last_known_years"] = (base["last_known_date"] - base["cod"]).dt.days / 365.25
    base = base[base["age_entry_years"] >= 0]
    rows = []
    for sig in sorted(config.RELIABILITY_SIGNATURES):
        seen_sites = {s for (s, sg) in have if sg == sig}
        missing = base[~base["site"].isin(seen_sites)]
        for row in missing.itertuples():
            if row.age_last_known_years <= row.age_entry_years:
                continue
            rows.append({
                "site": row.site, "signature": sig, "equipment_key": f"{row.site}|{sig}",
                "cod": row.cod, "entry_date": row.entry_date, "age_entry_years": row.age_entry_years,
                "last_known_date": row.last_known_date, "age_last_known_years": row.age_last_known_years,
                "spell_index": 0, "age_at_event_years": row.age_last_known_years,
                "duration_years": row.age_last_known_years - row.age_entry_years,
                "status": "S", "n_months": None, "max_D": None,
                "n_blocks": row.n_blocks, "n_affected_blocks": None,
                "mwdc": row.mwdc, "state": row.state, "utility": row.utility, "tech_class": row.tech_class,
            })
    log.info("adding %d never-failed (fully right-censored) spells across %d signatures",
              len(rows), len(config.RELIABILITY_SIGNATURES))
    return pd.concat([life, pd.DataFrame(rows)], ignore_index=True)


def main():
    episodes = pd.read_parquet("data/episodes.parquet")
    sites = pd.read_parquet("data/subsample_sites.parquet")
    smd = pd.read_parquet("data/site_month_dollars.parquet")

    window = site_observation_window(smd)
    n_blocks = compute_n_blocks(smd, sites)
    log.info("observation windows resolved for %d/%d sites; n_blocks source: %s",
              len(window), len(sites), n_blocks["n_blocks_source"].value_counts().to_dict())

    life, recur = build_life_records(episodes, sites, window, n_blocks)
    life = add_never_failed_sites(life, sites, window, n_blocks)

    bad_dur = life[life["duration_years"] < 0]
    assert len(bad_dur) == 0, f"negative-duration life records after truncation/censoring logic: {len(bad_dur)}"

    life = life.sort_values(["site", "signature", "spell_index"]).reset_index(drop=True)
    recur = recur.sort_values(["site", "signature", "interval_index"]).reset_index(drop=True)

    life.to_parquet("data/life_records.parquet", index=False)
    recur.to_parquet("data/recurrence_intervals.parquet", index=False)

    n_fail = (life["status"] == "F").sum()
    n_susp = (life["status"] == "S").sum()
    log.info("S12 complete: %d life records (%d failures, %d suspensions) across %d equipment_keys, "
              "%d recurrence intervals -> data/life_records.parquet, data/recurrence_intervals.parquet",
              len(life), n_fail, n_susp, life["equipment_key"].nunique(), len(recur))
    for sig in sorted(config.RELIABILITY_SIGNATURES):
        sub = life[life["signature"] == sig]
        log.info("  %-18s %5d failures / %5d suspensions across %d sites",
                  sig, (sub["status"] == "F").sum(), (sub["status"] == "S").sum(), sub["site"].nunique())


if __name__ == "__main__":
    main()
