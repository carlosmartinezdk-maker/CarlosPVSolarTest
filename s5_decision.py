"""
S5 - Decision matrix (lead determination). Uses PRI where a valid peer
group exists, PI_adj (Section 0.1 fallback) otherwise - same "score"
quantity S6 uses, so the two stay consistent by construction.
"""
import logging

import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S5 %(message)s")
log = logging.getLogger("s5")

T = config.PI_PRI_DECISION_THRESHOLD


def classify_quadrant(row) -> str:
    pri_proxy = row["PRI"] if row["benchmark_mode"] == "peer" else row["PI_adj"]
    if row.get("no_irradiance_year", False):
        # Section 0.7: 2026 has no PI/PR_T at all - never a qualified LEAD,
        # even where PRI alone flags. Surfaced distinctly so it isn't
        # confused with an ordinary unscored month.
        return "PRI_ONLY_UNCONFIRMED" if pd.notna(pri_proxy) else "insufficient_data"
    pi_ok = pd.notna(row["PI"]) and row["PI"] >= T
    pri_ok = pd.notna(pri_proxy) and pri_proxy >= T
    if pd.isna(row["PI"]) or pd.isna(pri_proxy):
        return "insufficient_data"
    if not pi_ok and not pri_ok:
        return "LEAD"
    if not pi_ok and pri_ok:
        return "REGIONAL_NOT_A_LEAD"
    if pi_ok and not pri_ok:
        return "PEER_GROUP_RECHECK"
    return "HEALTHY"


def main():
    df = pd.read_parquet("data/site_month_indices.parquet")
    df["quadrant"] = df.apply(classify_quadrant, axis=1)
    df["month_is_lead_candidate"] = df["quadrant"] == "LEAD"

    site_year_leads = (
        df.groupby(["site", "year"])["month_is_lead_candidate"].sum()
        .rename("lead_candidate_months").reset_index()
    )
    site_year_leads["is_lead"] = site_year_leads["lead_candidate_months"] >= 2

    df = df.merge(site_year_leads[["site", "year", "is_lead", "lead_candidate_months"]],
                  on=["site", "year"], how="left")

    df.to_parquet("data/site_month_decision.parquet", index=False)
    log.info("S5 complete: quadrant counts %s", df["quadrant"].value_counts().to_dict())
    log.info("site-years meeting lead bar (>=2 lead-candidate months): %d / %d",
              site_year_leads["is_lead"].sum(), len(site_year_leads))


if __name__ == "__main__":
    main()
