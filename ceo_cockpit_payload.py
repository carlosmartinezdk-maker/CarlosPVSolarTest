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


def build_map_sites(sites, account):
    """A4's minimal per-site map schema: site, owner, lat, lon, mwdc, cod,
    relationship, in_scope - for every geolocated site fleet-wide, not just
    the in-scope subset."""
    rel_map = dict(zip(account["owner_entity"], account["relationship"]))
    scope_map = dict(zip(account["owner_entity"], account["above_floor"]))
    out = []
    for _, s in sites.iterrows():
        if pd.isna(s.get("lat")) or pd.isna(s.get("lon")):
            continue
        owner = s["owner_entity"]
        out.append(dict(
            site=s["site"], owner=owner, lat=r(s["lat"], 3), lon=r(s["lon"], 3),
            mwdc=r(s["mwdc"], 1), cod=s["cod"] if pd.notna(s.get("cod")) else None,
            state=s["state"] if pd.notna(s.get("state")) else None,
            relationship=rel_map.get(owner, "Whitespace"),
            in_scope=bool(scope_map.get(owner, False)),
        ))
    return out


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
    in_scope_sites = sites[sites["owner_entity"].isin(in_scope_owners)]
    n_in_scope_sites = len(in_scope_sites)
    # B2: every section built on rel_* fields needs an explicit "based on X
    # of Y sites" statement - one coverage count per field, computed once
    # here against the in-scope site set so every screen agrees.
    rel_field_coverage = {
        field: dict(n=int(in_scope_sites[field].notna().sum()), of=n_in_scope_sites)
        for field in ("rel_n_blocks", "rel_insp_optimal_months", "rel_warranty_remaining_years")
    }
    site_cols = ["site", "state", "county", "operator", "mwdc", "lat", "lon", "cod", "tracking",
                 "conviction_tier", "top_signature", "fault_months", "episode_count",
                 "cost_of_inaction_usd", "recoverable_usd_yr", "recoverable_mwh_yr",
                 "latest_pi", "latest_pri", "latest_scored_month", "beta", "beta_t", "beta_excess",
                 "excess_category", "decision_grade", "warranty_urgent", "warranty_active",
                 "months", "pi", "pri", "capacity_suspect",
                 "rel_n_blocks", "rel_age_years", "rel_insp_optimal_months", "rel_insp_optimal_cost_usd",
                 "rel_insp_saving_usd", "rel_insp_scada_value_usd", "rel_warranty_remaining_years",
                 "rel_warranty_claim_value_usd",
                 "rel_p24_BLOCK_OUTAGE", "rel_p24_BOS_INTERMITTENT", "rel_p24_OUTAGE_FULL",
                 "rel_p24_SOILING", "rel_p24_TRACKER", "rel_p24_UNATTRIBUTED"]
    # B1: a capacity_suspect site's PI is physically impossible (bad MWdc
    # denominator, not real performance) - null the PI-derived fields so no
    # chart/table can render them, but keep the site row (mwdc, CoI, etc
    # stay) since the site's existence isn't in question, only its PI.
    PI_DERIVED_FIELDS = ("latest_pi", "pi")
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
            if row.get("capacity_suspect"):
                for f in PI_DERIVED_FIELDS:
                    row[f] = None
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
            generated_note="CEO Cockpit - pricing read from pricing.yaml (SaaS $120/MWdc/yr, "
                            "SCADA $48/MWdc/yr, fixed at source 17 Aug 2026 per "
                            "CEO_COCKPIT_REVISIONS_PASS2.md Part B3). explorer.html and this cockpit "
                            "derive their fee potential from the same pricing.yaml - see tests/test_pricing.py.",
            data_through_month=sites["latest_scored_month"].dropna().max() if sites["latest_scored_month"].notna().any() else None,
            rel_field_coverage=rel_field_coverage,
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
            # A4: every US solar site as its own dot, not an account-centroid
            # bubble - out-of-scope sites (below the 250 MWdc floor) are
            # included too so the map reads as the whole fleet, not just the
            # engaged slice. ~6,200 rows x 7 small fields, well inside budget.
            map_sites=build_map_sites(sites, account),
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
            # A6b "what breaks next": mean time to repair per fault type,
            # fleet-wide pooled (same caveat as the Weibull fits - not
            # decomposable by account).
            mttr_by_signature=[dict(signature=m["signature"], mttr_months=r(m["mttr_months"], 1),
                                     median_months=r(m["median_months"], 1), n=ri(m["n"]))
                                for m in fits.get("mttr_diagnostic", [])],
        ),
        coverage=dict(
            book=book_out, total_coi=r(coverage["total_coi"]), assigned=r(coverage["assigned"]),
            unassigned=r(coverage["unassigned"]), whitespace=r(coverage["whitespace"]),
            n_reps_named=coverage["n_reps_named"], matched_gtm_accounts=coverage["matched_gtm_accounts"],
            crm_rows=coverage["crm_rows"],
        ),
    )
    return sanitize(payload)
