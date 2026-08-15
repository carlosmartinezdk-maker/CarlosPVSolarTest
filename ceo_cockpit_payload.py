"""Payload assembly for ceo_cockpit.html - imported by s18_ceo_cockpit.py.
Kept separate so the account/matching/plays logic in s18 stays readable."""
import json
import math

import numpy as np
import pandas as pd


def sanitize(obj):
    """Recursively replace NaN/NaT/pandas-missing with None - json.dumps
    otherwise emits the bare token NaN, which is not valid JSON and breaks
    JSON.parse in the browser (this bites list-valued fields like the
    per-site pi/pri monthly series, which the scalar rounding helpers
    below don't touch)."""
    if isinstance(obj, dict):
        return {k: sanitize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [sanitize(v) for v in obj]
    if isinstance(obj, float) and math.isnan(obj):
        return None
    try:
        if pd.isna(obj):
            return None
    except (TypeError, ValueError):
        pass
    return obj


def r(v, nd=0):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return None
    return round(float(v), nd)


def ri(v):
    if v is None or (isinstance(v, float) and pd.isna(v)):
        return None
    return int(v)


def build_payload(sites, account, in_scope, plays, coverage, gtm, whitespace_all_pct, total_coi_all):
    in_scope = in_scope.sort_values("coi_3yr_usd", ascending=False)

    accounts_out = []
    for _, a in in_scope.iterrows():
        accounts_out.append(dict(
            owner_entity=a["owner_entity"], relationship=a["relationship"],
            n_sites=ri(a["n_sites"]), mwdc=r(a["mwdc"], 1), states=a["states"],
            coi_3yr_usd=r(a["coi_3yr_usd"]), recoverable_usd_yr=r(a["recoverable_usd_yr"]),
            fee_annual_usd=r(a["fee_annual_usd"]), fee_as_pct_of_loss=r(a["fee_as_pct_of_loss"], 4),
            payback_weeks=r(a["payback_weeks"], 1), confidence=a["confidence"],
            ownership_unresolved=bool(a["ownership_unresolved"]),
            top_signature=a["top_signature_mode"], focus_band=a["focus_band"], focus_reason=a["focus_reason"],
            account_owner=a["account_owner"] if pd.notna(a["account_owner"]) else None,
            gtm_matched_account=a["gtm_matched_account"] if pd.notna(a["gtm_matched_account"]) else None,
            has_solar_inspections=bool(a["has_solar_inspections"]), has_solar_saas=bool(a["has_solar_saas"]),
            has_rvm=bool(a["has_rvm"]), has_performance=bool(a["has_performance"]),
            warranty_urgent_n=ri(a["warranty_urgent_n"]),
        ))

    plays_out = []
    for _, p in plays.iterrows():
        plays_out.append(dict(
            play_id=p["play_id"], account=p["account"], signature=p["signature"],
            n_sites=ri(p["n_sites"]), states=p["states"], mwdc=r(p["mwdc"], 1),
            recoverable_usd_yr=r(p["recoverable_usd_yr"]), coi_3yr_usd=r(p["coi_3yr_usd"]),
            offering=p["offering"], annual_fee_usd=r(p["annual_fee_usd"]),
            payback_weeks=r(p["payback_weeks"], 1), pitch_sentence=p["pitch_sentence"],
            confidence=p["confidence"], sites=p["sites"],
        ))

    # per-account site detail, in-scope only (keeps payload small - test 63)
    in_scope_owners = set(in_scope["owner_entity"])
    site_cols = ["site", "state", "county", "operator", "mwdc", "lat", "lon", "cod", "tracking",
                 "conviction_tier", "top_signature", "fault_months", "episode_count",
                 "cost_of_inaction_usd", "recoverable_usd_yr", "recoverable_mwh_yr",
                 "latest_pi", "latest_pri", "latest_scored_month", "beta", "beta_t", "beta_excess",
                 "excess_category", "decision_grade", "warranty_urgent", "warranty_active",
                 "months", "pi", "pri",
                 "rel_n_blocks", "rel_age_years", "rel_insp_optimal_months", "rel_insp_optimal_cost_usd",
                 "rel_insp_saving_usd", "rel_insp_scada_value_usd", "rel_warranty_remaining_years",
                 "rel_warranty_claim_value_usd"]
    sites_by_account = {}
    for owner, g in sites[sites["owner_entity"].isin(in_scope_owners)].groupby("owner_entity"):
        rows = []
        for _, s in g.iterrows():
            row = {}
            for c in site_cols:
                v = s.get(c)
                if isinstance(v, float):
                    v = r(v, 4)
                elif isinstance(v, (np.integer,)):
                    v = int(v)
                elif isinstance(v, (list, np.ndarray)):
                    v = list(v)
                elif isinstance(v, (bool, np.bool_)):
                    v = bool(v)
                row[c] = v
            rows.append(row)
        sites_by_account[owner] = rows

    with open("ceo_cockpit/data/reliability_fits.json") as f:
        fits = json.load(f)
    hazard = pd.read_parquet("ceo_cockpit/data/hazard_by_age.parquet")
    hazard_out = [dict(signature=row["signature"], age_low=r(row["age_band_low"], 0),
                        age_high=r(row["age_band_high"], 0),
                        hazard_rate=r(row["hazard_rate"], 4) if pd.notna(row["hazard_rate"]) else None,
                        exposure_years=r(row["exposure_years"], 1)) for _, row in hazard.iterrows()]

    book_out = []
    for _, b in coverage["book_df"].iterrows():
        book_out.append(dict(
            rep=b["rep"], market_status=b["market_status"], n_accounts=ri(b["n_accounts"]),
            n_customer=ri(b["n_customer"]), n_prospect=ri(b["n_prospect"]), mwdc=r(b["mwdc"], 1),
            recoverable_usd_yr=r(b["recoverable_usd_yr"]), coi_3yr_usd=r(b["coi_3yr_usd"]),
            book_concentration=r(b["book_concentration"], 3),
            single_logo=bool(b["book_concentration"] and b["book_concentration"] > 0.8),
        ))

    payload = dict(
        meta=dict(
            generated_note="CEO Cockpit - pricing corrected locally per spec Section 1.1 "
                            "(SaaS $120/MWdc/yr, SCADA $48/MWdc/yr, both x12 from pricing.yaml's "
                            "uncorrected rate - see ceo_cockpit/README.md). pricing.yaml itself and "
                            "explorer.html are NOT yet updated - that is a separate pending decision.",
            engagement_floor_mwdc=250,
            total_accounts_all=ri(len(account)),
            total_coi_all_usd=r(total_coi_all),
            whitespace_share_all_estimate=r(whitespace_all_pct, 3),
            in_scope_accounts=ri(len(in_scope)),
            in_scope_coi_usd=r(in_scope["coi_3yr_usd"].sum()),
            in_scope_fee_potential_usd=r(in_scope["fee_annual_usd"].sum()),
            matched_gtm_accounts=coverage["matched_gtm_accounts"],
        ),
        screen1=dict(
            waterfall=dict(
                total_coi_all=r(total_coi_all),
                in_scope_coi=r(in_scope["coi_3yr_usd"].sum()),
                customer_coi=r(in_scope.loc[in_scope["relationship"] == "Customer", "coi_3yr_usd"].sum()),
                prospect_coi=r(in_scope.loc[in_scope["relationship"] == "Prospect", "coi_3yr_usd"].sum()),
                whitespace_coi=r(in_scope.loc[in_scope["relationship"] == "Whitespace", "coi_3yr_usd"].sum()),
            ),
            map_bubbles=[
                dict(owner=owner, lat=r(g["lat"].mean(), 3), lon=r(g["lon"].mean(), 3),
                     coi=r(g["cost_of_inaction_usd"].fillna(0).sum()),
                     relationship=in_scope.loc[in_scope["owner_entity"] == owner, "relationship"].iloc[0]
                     if owner in in_scope_owners else "below_floor")
                for owner, g in sites[sites["owner_entity"].isin(in_scope_owners)].groupby("owner_entity")
                if g["lat"].notna().any()
            ],
        ),
        accounts=accounts_out,
        plays=plays_out,
        sites_by_account=sites_by_account,
        reliability=dict(
            signatures=[dict(signature=s["signature"], best_fit_family=s["best_fit"]["family"],
                              weibull_beta=r(s["weibull_beta"], 3), weibull_eta_years=r(s["weibull_eta_years"], 2),
                              beta_classification=s["beta_classification"], rvm_eligible=s["rvm_eligible"],
                              n_failures=s["n_failures"], n_suspensions=s["n_suspensions"])
                        for s in fits["signatures"]],
            hazard_by_age=hazard_out,
        ),
        coverage=dict(
            book=book_out, total_coi=r(coverage["total_coi"]), assigned=r(coverage["assigned"]),
            unassigned=r(coverage["unassigned"]), whitespace=r(coverage["whitespace"]),
            n_reps_named=coverage["n_reps_named"], matched_gtm_accounts=coverage["matched_gtm_accounts"],
            crm_rows=coverage["crm_rows"],
        ),
    )
    return sanitize(payload)
