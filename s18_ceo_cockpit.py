"""
S18 - CEO Cockpit build (ceo_cockpit/spec/CEO_COCKPIT_SPEC.md).

Second, CFO-facing HTML alongside explorer.html. Reads the site-level
export in ceo_cockpit/data/ (produced from the already-tested
explorer.html payload, not recomputed) plus Carlos's GTM accounts and
SPV-to-parent-company mapping. Builds account/owner rollups, a "plays"
table (account x dominant fault pattern), GTM relationship matching, rep
coverage, and CRM reconciliation, then renders ceo_cockpit.html.

PRICING: pricing.yaml is the single source of truth for SaaS/SCADA rates
(CEO_COCKPIT_REVISIONS_PASS2.md Part B3 - the earlier "fix it locally in
the cockpit only" approach was explicitly reversed once explorer.html and
this tool started reporting different fee potential for the same fleet).
Fee is still recomputed from mwdc x recommended_offerings rather than
read off the site-level annual_fee_usd column, because that column's
fee mix (which offerings, at what severity-driven RVM add-ons) can differ
from what this tool wants to show - but the RATE CONSTANTS themselves
come from pricing.yaml, not a local copy. See tests/test_pricing.py.
"""
import csv
import json
import logging
import re

import numpy as np
import pandas as pd
import yaml

logging.basicConfig(level=logging.INFO, format="%(asctime)s S18 %(message)s")
log = logging.getLogger("s18")

DATA_DIR = "ceo_cockpit/data"
SPEC_DIR = "ceo_cockpit/spec"
HORIZON_YEARS = 3                          # matches pricing.yaml's horizon_years
ENGAGEMENT_FLOOR_MWDC = 250.0


def load_pricing(path: str = "pricing.yaml") -> dict:
    with open(path) as f:
        return yaml.safe_load(f)


def corrected_site_fee(offerings: list, mwdc: float, pricing: dict) -> float:
    off = pricing["offerings"]
    fee = 0.0
    if "Solar SaaS" in offerings:
        fee += off["solar_saas"]["usd_per_mwdc_year"] * (mwdc or 0)
    if "SCADA Monitoring" in offerings:
        fee += off["scada_monitoring"]["usd_per_mwdc_year"] * (mwdc or 0)
    if "Recurrent Inspection" in offerings:
        fee += off["solar_inspection"]["usd_per_mwdc_inspected"] * off["solar_inspection"]["inspections_per_year"] * (mwdc or 0)
    return fee


# --------------------------------------------------------------------------
# Capacity-suspect quarantine (CEO_COCKPIT_REVISIONS_PASS2.md Part B1): a PI
# of 52 means a site produced 52x what physics allows - the cause is a
# capacity (MWdc) denominator that's wrong, not real performance. Flag on
# the trailing 12-month median PI so one bad month doesn't quarantine a
# site, and everything downstream can suppress the bogus PI-derived
# figures without pretending the site doesn't exist.
# --------------------------------------------------------------------------
CAPACITY_SUSPECT_PI_THRESHOLD = 1.35


def median_trailing12_pi(pi_series) -> float:
    if pi_series is None:
        return np.nan
    vals = [v for v in list(pi_series)[-12:] if v is not None and not (isinstance(v, float) and np.isnan(v))]
    return float(np.median(vals)) if vals else np.nan


def flag_capacity_suspect(sites: pd.DataFrame) -> pd.DataFrame:
    sites = sites.copy()
    sites["median_pi_12mo"] = sites["pi"].apply(median_trailing12_pi)
    sites["capacity_suspect"] = sites["median_pi_12mo"] > CAPACITY_SUSPECT_PI_THRESHOLD
    n = int(sites["capacity_suspect"].sum())
    log.info("capacity_suspect: %d/%d sites flagged (trailing 12mo median PI > %.2f)",
              n, len(sites), CAPACITY_SUSPECT_PI_THRESHOLD)
    return sites


def write_capacity_suspect_csv(sites: pd.DataFrame, path: str) -> None:
    flagged = sites.loc[sites["capacity_suspect"],
                         ["site", "owner_entity", "utility", "state", "mwdc", "median_pi_12mo", "latest_pi"]]
    flagged = flagged.sort_values("median_pi_12mo", ascending=False)
    flagged.to_csv(path, index=False)
    log.info("wrote %s: %d sites for a data fix (capacity/MWdc denominator)", path, len(flagged))


# --------------------------------------------------------------------------
# Owner rollup (Section 1.2): parent_company where resolved, else utility
# --------------------------------------------------------------------------
def load_parent_map(path: str) -> dict:
    m = {}
    with open(path) as f:
        for row in csv.DictReader(f):
            if row["parent_company"]:
                m[row["spv_name"]] = row["parent_company"]
    return m


def resolve_owner_entity(df: pd.DataFrame, parent_map: dict) -> pd.DataFrame:
    df = df.copy()
    df["owner_entity"] = df["utility"].map(parent_map).fillna(df["utility"])
    df["owner_source"] = np.where(df["utility"].isin(parent_map), "parent_mapping", "utility")
    return df


# --------------------------------------------------------------------------
# GTM matcher (Section 1.3, the "Required" fuller version)
# --------------------------------------------------------------------------
STOPWORDS = {
    "llc", "inc", "lp", "llp", "ltd", "corp", "corporation", "company", "co",
    "holdings", "holding", "group", "energy", "energies", "renewable",
    "renewables", "power", "solar", "resources", "generation", "clean",
    "us", "usa", "america", "american", "north", "the", "plc", "gmbh", "ag",
    "nv", "sa", "srl", "na", "nam", "eu", "europe", "vind", "vindkraft",
}
PAREN_RE = re.compile(r"\(([^)]*)\)")
PUNCT_RE = re.compile(r"[.,'\-/&]")


def normalize_tokens(name: str) -> frozenset:
    """Tokens of length < 3 are dropped along with stopwords - short/numeric
    fragments like the '(2)' in 'Greenbacker (2)' (a GTM duplicate-row
    marker, not a real alias) would otherwise become a trivial subset of
    almost any other name and cause false-positive matches."""
    if not name:
        return frozenset()
    s = PAREN_RE.sub(" ", name)
    s = PUNCT_RE.sub(" ", s).lower()
    tokens = [t for t in s.split() if len(t) >= 3 and t not in STOPWORDS]
    return frozenset(tokens)


def alias_candidates(name: str) -> list:
    """The parenthetical content is itself often the real matchable name
    ('AES (AES Clean Energy)' -> 'AES Clean Energy' is our fleet's utility
    string) - generate it as a second candidate alongside the main name."""
    cands = [name]
    for m in PAREN_RE.finditer(name or ""):
        if m.group(1).strip():
            cands.append(m.group(1).strip())
    return cands


def build_gtm_index(gtm: pd.DataFrame, fleet_owner_entities: list) -> dict:
    """token-frozenset -> list of gtm row indices, built from account,
    ultimate_parent, and any parenthetical alias of either.

    Single-token keys are the risky case - a generic word like 'capital'
    or 'southern' is technically a substring match for several unrelated
    companies (TLS Capital / NuGen Capital / Capital Power; Southern
    California Edison / Southern Power) and a false match here would
    misdirect a real sales conversation, which the spec is explicit is
    the failure mode to avoid. Rather than hand-curate an ever-growing
    stopword list, detect ambiguity from the FLEET side: if a token
    appears in more than one distinct fleet owner_entity's name, it is
    not a reliable identifier (the GTM side alone can't reveal this,
    since e.g. 'Capital Power' is the only GTM row with 'capital' - the
    collision only shows up once you look at how many different fleet
    owners that same token would also match)."""
    fleet_token_freq = {}
    for name in fleet_owner_entities:
        for tok in normalize_tokens(name):
            fleet_token_freq.setdefault(tok, set()).add(name)
    ambiguous = {tok for tok, owners in fleet_token_freq.items() if len(owners) > 1}

    index = {}
    first_token_index = {}
    for i, row in gtm.iterrows():
        names = set()
        for field in ("account", "ultimate_parent"):
            val = row.get(field)
            if isinstance(val, str) and val.strip():
                names.update(alias_candidates(val))
        for name in names:
            toks = normalize_tokens(name)
            if toks and not (len(toks) == 1 and next(iter(toks)) in ambiguous):
                index.setdefault(toks, []).append(i)
            first_toks = [t for t in PUNCT_RE.sub(" ", PAREN_RE.sub(" ", name)).lower().split()
                          if len(t) >= 3 and t not in STOPWORDS]
            if first_toks and len(first_toks[0]) >= 4 and first_toks[0] not in ambiguous:
                first_token_index.setdefault(first_toks[0], []).append(i)
    return {"exact": index, "first_token": first_token_index, "ambiguous": ambiguous}


def match_owner(owner_entity: str, gtm_index: dict, gtm: pd.DataFrame) -> tuple:
    toks = normalize_tokens(owner_entity)
    if toks and toks in gtm_index["exact"]:
        return gtm.loc[gtm_index["exact"][toks][0]], "exact_token_set"
    if not toks:
        return None, None
    # subset/superset overlap - e.g. "NextEra" subset of "NextEra Energy
    # Resources". A subset match is only as safe as its SMALLER side: an
    # ambiguous token (fleet-side collision) or a bare fragment left over
    # after stripping (e.g. 'Fu-Gen' loses 'Fu' as too-short, leaving the
    # meaningless single token 'gen') must not be allowed to carry a
    # match on its own, even as part of a larger candidate set.
    best = None
    for cand_toks, idxs in gtm_index["exact"].items():
        if not cand_toks:
            continue
        smaller = toks if len(toks) <= len(cand_toks) else cand_toks
        if len(smaller) == 1:
            tok = next(iter(smaller))
            if tok in gtm_index["ambiguous"] or len(tok) < 5:
                continue
        if toks <= cand_toks or cand_toks <= toks:
            best = idxs[0]
            break
    if best is not None:
        return gtm.loc[best], "token_subset"
    first_toks = [t for t in PUNCT_RE.sub(" ", PAREN_RE.sub(" ", owner_entity)).lower().split()
                  if len(t) >= 3 and t not in STOPWORDS]
    if (first_toks and len(first_toks[0]) >= 4 and first_toks[0] not in gtm_index["ambiguous"]
            and first_toks[0] in gtm_index["first_token"]):
        return gtm.loc[gtm_index["first_token"][first_toks[0]][0]], "first_token"
    return None, None


def match_all_owners(account_df: pd.DataFrame, gtm: pd.DataFrame) -> pd.DataFrame:
    gtm_index = build_gtm_index(gtm, account_df["owner_entity"].tolist())
    rels, matched_names, methods = [], [], []
    owners_held = {"has_solar_inspections": [], "has_solar_saas": [], "has_rvm": [], "has_performance": []}
    account_owner_col, gtm_mw_col = [], []
    for owner in account_df["owner_entity"]:
        row, method = match_owner(owner, gtm_index, gtm)
        if row is None:
            rels.append("Whitespace"); matched_names.append(None); methods.append(None)
            for k in owners_held:
                owners_held[k].append(False)
            account_owner_col.append(None); gtm_mw_col.append(None)
        else:
            rel = row.get("relationship") or "Prospect"
            rels.append(rel if rel in ("Customer", "Prospect") else "Prospect")
            matched_names.append(row.get("account"))
            methods.append(method)
            for k in owners_held:
                owners_held[k].append(bool(row.get(k)) if pd.notna(row.get(k)) else False)
            account_owner_col.append(row.get("account_owner") or None)
            gtm_mw_col.append(row.get("gtm_solar_mw") if pd.notna(row.get("gtm_solar_mw")) else None)
    account_df = account_df.copy()
    account_df["relationship"] = rels
    account_df["gtm_matched_account"] = matched_names
    account_df["gtm_match_method"] = methods
    for k, v in owners_held.items():
        account_df[k] = v
    account_df["account_owner"] = account_owner_col
    account_df["gtm_solar_mw"] = gtm_mw_col
    return account_df


# --------------------------------------------------------------------------
# Account rollup
# --------------------------------------------------------------------------
# --------------------------------------------------------------------------
# Pass 3 Section 2.2: "what is this account worth at full attach", as
# distinct from fee_annual_usd (the "lead-offering fee" - what we'd charge
# if a site bought only the one product we lead with). Never summed with
# fee_annual_usd - see CEO_COCKPIT_REVISIONS_PASS3.md Part 2.2's explicit
# "never sum them".
# --------------------------------------------------------------------------
def software_revenue_usd_yr(mwdc: float, pricing: dict) -> float:
    off = pricing["offerings"]
    rate = off["solar_saas"]["usd_per_mwdc_year"] + off["scada_monitoring"]["usd_per_mwdc_year"]
    return (mwdc or 0) * rate


def inspection_revenue_usd_yr(mwdc: float, optimal_months, pricing: dict) -> float:
    off = pricing["offerings"]
    visits = 12.0 / optimal_months if optimal_months and not pd.isna(optimal_months) else 1.0
    return (mwdc or 0) * off["solar_inspection"]["usd_per_mwdc_inspected"] * visits


def build_account_table(sites: pd.DataFrame, pricing: dict) -> pd.DataFrame:
    sites = sites.copy()
    sites["_offerings_list"] = sites["recommended_offerings"].fillna("").apply(
        lambda s: [x for x in s.split(";") if x])
    sites["_fee_corrected"] = sites.apply(
        lambda r: corrected_site_fee(r["_offerings_list"], r["mwdc"], pricing), axis=1)
    sites["_software_rev"] = sites["mwdc"].apply(lambda m: software_revenue_usd_yr(m, pricing))
    sites["_inspection_rev"] = sites.apply(
        lambda r: inspection_revenue_usd_yr(r["mwdc"], r.get("rel_insp_optimal_months"), pricing), axis=1)
    sites["_inspection_fitted"] = sites["rel_insp_optimal_months"].notna()

    g = sites.groupby("owner_entity")
    acct = g.agg(
        n_sites=("site", "count"),
        mwdc=("mwdc", "sum"),
        states=("state", lambda s: sorted(set(x for x in s if pd.notna(x)))),
        coi_3yr_usd=("cost_of_inaction_usd", lambda s: s.fillna(0).sum()),
        recoverable_usd_yr=("recoverable_usd_yr", lambda s: s.fillna(0).sum()),
        recoverable_mwh_yr=("recoverable_mwh_yr", lambda s: s.fillna(0).sum()),
        fee_annual_usd=("_fee_corrected", "sum"),
        software_revenue_usd_yr=("_software_rev", "sum"),
        inspection_revenue_usd_yr=("_inspection_rev", "sum"),
        n_sites_insp_fitted=("_inspection_fitted", "sum"),
        warranty_urgent_n=("warranty_urgent", "sum"),
        pri_benchmarked_pct=("latest_pri", lambda s: s.notna().mean()),
        median_years_present=("years_present", "median"),
        owner_source=("owner_source", "first"),
        top_signature_mode=("top_signature", lambda s: s.mode().iloc[0] if len(s.mode()) else None),
    ).reset_index()

    acct["total_ssi_potential_usd_yr"] = acct["software_revenue_usd_yr"] + acct["inspection_revenue_usd_yr"]
    acct["fee_as_pct_of_loss"] = np.where(acct["recoverable_usd_yr"] > 0,
                                           acct["fee_annual_usd"] / acct["recoverable_usd_yr"], np.nan)
    acct["payback_weeks"] = np.where(
        acct["recoverable_usd_yr"] > 0,
        52 * acct["fee_annual_usd"] / (acct["recoverable_usd_yr"] * 0.85), np.nan)
    acct["ownership_unresolved"] = (acct["owner_source"] == "utility") & (acct["n_sites"] <= 2)
    acct["confidence"] = np.select(
        [
            (~acct["ownership_unresolved"]) & (acct["pri_benchmarked_pct"] >= 0.6) & (acct["median_years_present"] >= 4),
            (~acct["ownership_unresolved"]).astype(int) + (acct["pri_benchmarked_pct"] >= 0.6).astype(int)
            + (acct["median_years_present"] >= 4).astype(int) >= 2,
        ],
        ["high", "medium"], default="low")
    acct["above_floor"] = acct["mwdc"] >= ENGAGEMENT_FLOOR_MWDC
    return acct


# --------------------------------------------------------------------------
# Plays (Section 3): account x dominant fault pattern
# --------------------------------------------------------------------------
def fmt_usd(v: float) -> str:
    """A3's money rule (CEO_COCKPIT_REVISIONS_PASS2.md), applied server-side
    too - pitch_sentence is plain text baked at build time, not re-formatted
    by the template's JS fmt utility, so it has to follow the same rule."""
    av = abs(v)
    if av >= 1e6:
        return f"${v/1e6:,.1f}M"
    return f"${v:,.0f}"


def fmt_mwdc(v: float) -> str:
    return f"{v:,.1f}"


PITCH_TEMPLATES = {
    "SOILING": "{n} of your {region} plants ({mwdc} MWdc) are losing production to soiling. "
               "A cleaning programme recovers an estimated {rec}/yr against a {fee} inspection fee.",
    "BLOCK_OUTAGE": "{n} of your {region} plants ({mwdc} MWdc) are carrying repeat block outages. "
                    "Recurrent inspection plus coordinated repair recovers an estimated {rec}/yr against a {fee} fee.",
    "OUTAGE_FULL": "{n} of your {region} plants ({mwdc} MWdc) have had full-site outages. "
                   "SCADA monitoring would catch the next one in hours, not months - an estimated {rec}/yr at stake against a {fee} fee.",
    "TRACKER": "{n} of your {region} plants ({mwdc} MWdc) show tracker misalignment. "
               "An inspection and controller check recovers an estimated {rec}/yr against a {fee} fee.",
    "BOS_INTERMITTENT": "{n} of your {region} plants ({mwdc} MWdc) show intermittent BOS faults. "
                        "Aerial IR plus string-level inspection recovers an estimated {rec}/yr against a {fee} fee.",
    "UNATTRIBUTED": "{n} of your {region} plants ({mwdc} MWdc) are underperforming without a confirmed cause yet. "
                    "A full site diagnostic is the first step - an estimated {rec}/yr is unexplained.",
}
SIGNATURE_OFFERING = {
    "SOILING": "Recurrent Inspection", "BLOCK_OUTAGE": "Recurrent Inspection",
    "OUTAGE_FULL": "SCADA Monitoring", "TRACKER": "Recurrent Inspection",
    "BOS_INTERMITTENT": "Recurrent Inspection", "UNATTRIBUTED": "Recurrent Inspection",
}


def build_plays(sites: pd.DataFrame, pricing: dict) -> pd.DataFrame:
    sites = sites.copy()
    sites["_offerings_list"] = sites["recommended_offerings"].fillna("").apply(
        lambda s: [x for x in s.split(";") if x])
    sites["_fee_corrected"] = sites.apply(
        lambda r: corrected_site_fee(r["_offerings_list"], r["mwdc"], pricing), axis=1)

    plays = []
    pid = 0
    for (owner, sig), g in sites.groupby(["owner_entity", "top_signature"]):
        if sig in (None, "NONE", "UNSCORED", "WATCH_NOT_A_FAULT"):
            continue
        coi = g["cost_of_inaction_usd"].fillna(0).sum()
        if len(g) < 2 and coi < 1_000_000:
            continue
        states = sorted(set(x for x in g["state"] if pd.notna(x)))
        region = states[0] if len(states) == 1 else f"{len(states)}-state"
        mwdc = g["mwdc"].fillna(0).sum()
        rec = g["recoverable_usd_yr"].fillna(0).sum()
        offering = SIGNATURE_OFFERING.get(sig, "Recurrent Inspection")
        fee = corrected_site_fee([offering], mwdc, pricing)
        template = PITCH_TEMPLATES.get(sig, PITCH_TEMPLATES["UNATTRIBUTED"])
        pitch = template.format(n=len(g), region=region, mwdc=fmt_mwdc(mwdc), rec=fmt_usd(rec), fee=fmt_usd(max(fee, 1)))
        pid += 1
        plays.append(dict(
            play_id=f"P{pid:04d}", account=owner, signature=sig, n_sites=len(g),
            states=states, mwdc=round(mwdc, 1), recoverable_usd_yr=round(rec, 0),
            coi_3yr_usd=round(coi, 0), offering=offering, annual_fee_usd=round(fee, 0),
            payback_weeks=round(52 * fee / (rec * 0.85), 1) if rec > 0 and fee > 0 else None,
            pitch_sentence=pitch, confidence="high" if len(g) >= 3 else "medium",
            sites=g["site"].tolist(),
        ))
    return pd.DataFrame(plays)


# --------------------------------------------------------------------------
# Focus bands (Section 5b-ii)
# --------------------------------------------------------------------------
def assign_focus_band(row) -> tuple:
    if row["mwdc"] < ENGAGEMENT_FLOOR_MWDC or row["ownership_unresolved"]:
        return "PARK", "Out of scope or un-callable until ownership is resolved"
    payback_wk = row.get("payback_weeks")
    if (row["coi_3yr_usd"] >= 10_000_000 and payback_wk is not None and payback_wk < 8
            and row["confidence"] != "low"):
        return "FOCUS_NOW", "Large, fast payback, and we trust the number"
    if row["relationship"] == "Customer":
        missing = [off for off, held in [
            ("Recurrent Inspection", row.get("has_solar_inspections")),
            ("Solar SaaS", row.get("has_solar_saas")),
            ("RVM", row.get("has_rvm")),
        ] if row.get("top_signature_mode") and off == SIGNATURE_OFFERING.get(row["top_signature_mode"]) and not held]
        if missing:
            return "EXPAND", "Existing customer, missing product"
    if row["relationship"] == "Whitespace" and row["coi_3yr_usd"] >= 5_000_000:
        return "NEW_LOGO", "Unworked account above the engagement floor"
    if row["coi_3yr_usd"] >= 2_000_000 and (payback_wk is None or payback_wk > 26 or row["confidence"] == "low"):
        return "NURTURE", "Real but slow, or we need better data first"
    return "NURTURE", "Real but slow, or we need better data first"


# --------------------------------------------------------------------------
# Rep coverage (Section 5) + CRM reconciliation (5c)
# --------------------------------------------------------------------------
EU_ONLY_REPS = None  # computed at runtime from gtm market column


def build_rep_coverage(account_df: pd.DataFrame, gtm: pd.DataFrame, n_matched_gtm_accounts: int) -> dict:
    in_scope = account_df[account_df["above_floor"]].copy()

    reps_all = gtm["account_owner"].dropna().unique().tolist()
    rep_market = {}
    # A9: "accounts managed" is the rep's full book across all technologies,
    # not just the US solar fleet - counted from gtm_accounts.csv directly,
    # not from anything derived here.
    n_managed = gtm["account_owner"].value_counts()
    for rep in reps_all:
        markets = set(gtm.loc[gtm["account_owner"] == rep, "market"].dropna())
        rep_market[rep] = "EU_ONLY" if markets and markets == {"EU"} else "NAM_OR_MIXED"

    in_scope["book"] = np.where(in_scope["relationship"] == "Whitespace", "WHITESPACE",
                                 np.where(in_scope["account_owner"].isna(), "UNASSIGNED", in_scope["account_owner"]))

    book_rows = []
    for book, g in in_scope.groupby("book"):
        book_rows.append(dict(
            rep=book, market_status=rep_market.get(book, "NAM_OR_MIXED" if book not in ("WHITESPACE", "UNASSIGNED") else None),
            n_accounts_managed=int(n_managed.get(book, 0)) if book not in ("WHITESPACE", "UNASSIGNED") else None,
            n_accounts=len(g), n_customer=int((g["relationship"] == "Customer").sum()),
            n_prospect=int((g["relationship"] == "Prospect").sum()),
            mwdc=round(g["mwdc"].sum(), 1), recoverable_usd_yr=round(g["recoverable_usd_yr"].sum(), 0),
            coi_3yr_usd=round(g["coi_3yr_usd"].sum(), 0),
        ))
    book_df = pd.DataFrame(book_rows).sort_values("coi_3yr_usd", ascending=False)

    total_coi = in_scope["coi_3yr_usd"].sum()
    assigned = in_scope.loc[(in_scope["relationship"] != "Whitespace") & in_scope["account_owner"].notna(), "coi_3yr_usd"].sum()
    unassigned = in_scope.loc[(in_scope["relationship"] != "Whitespace") & in_scope["account_owner"].isna(), "coi_3yr_usd"].sum()
    whitespace = in_scope.loc[in_scope["relationship"] == "Whitespace", "coi_3yr_usd"].sum()

    return dict(
        book_df=book_df, total_coi=total_coi, assigned=assigned, unassigned=unassigned,
        whitespace=whitespace, matched_gtm_accounts=n_matched_gtm_accounts,
        n_reps_named=len([r for r in reps_all if rep_market.get(r) != "EU_ONLY"]),
    )


def r(v, nd=0):
    if v is None or (isinstance(v, float) and (pd.isna(v) or np.isinf(v))):
        return None
    return round(float(v), nd)


def main():
    pricing = load_pricing()
    sites = pd.read_parquet(f"{DATA_DIR}/site_summary.parquet")
    gtm = pd.read_csv(f"{SPEC_DIR}/gtm_accounts.csv")
    parent_map = load_parent_map(f"{SPEC_DIR}/parent_mapping.csv")

    sites = resolve_owner_entity(sites, parent_map)
    log.info("owner rollup: %d sites -> %d owner_entities (%d resolved via parent_mapping)",
              len(sites), sites["owner_entity"].nunique(), (sites["owner_source"] == "parent_mapping").sum())

    sites = flag_capacity_suspect(sites)
    write_capacity_suspect_csv(sites, f"{DATA_DIR}/capacity_suspect.csv")

    account = build_account_table(sites, pricing)
    account = match_all_owners(account, gtm)
    n_matched = account["gtm_matched_account"].notna().sum()
    log.info("GTM match: %d/%d owner_entities matched (%.1f%%)", n_matched, len(account),
              100 * n_matched / len(account))

    in_scope = account[account["above_floor"]].copy()
    log.info("250 MWdc floor: %d accounts, $%.0fM CoI in scope (of %d total, $%.0fM)",
              len(in_scope), in_scope["coi_3yr_usd"].sum() / 1e6, len(account), account["coi_3yr_usd"].sum() / 1e6)

    unmatched_above_floor = in_scope[in_scope["relationship"] == "Whitespace"][
        ["owner_entity", "mwdc", "coi_3yr_usd", "n_sites"]].sort_values("mwdc", ascending=False)
    unmatched_above_floor.to_csv("ceo_cockpit/data/unmatched_owners.csv", index=False)
    log.info("wrote ceo_cockpit/data/unmatched_owners.csv: %d unmatched owners above %.0f MWdc",
              len(unmatched_above_floor), ENGAGEMENT_FLOOR_MWDC)

    bands = in_scope.apply(lambda r_: pd.Series(assign_focus_band(r_), index=["focus_band", "focus_reason"]), axis=1)
    in_scope = pd.concat([in_scope, bands], axis=1)

    plays_all = build_plays(sites, pricing)
    in_scope_owners = set(in_scope["owner_entity"])
    plays = plays_all[plays_all["account"].isin(in_scope_owners)].sort_values("coi_3yr_usd", ascending=False)
    log.info("plays: %d generated across %d in-scope accounts", len(plays), plays["account"].nunique())

    n_matched_gtm_accounts = account["gtm_matched_account"].dropna().nunique()
    log.info("distinct GTM accounts matched: %d/%d", n_matched_gtm_accounts, len(gtm))
    coverage = build_rep_coverage(in_scope, gtm, n_matched_gtm_accounts)
    log.info("coverage: assigned $%.0fM | unassigned $%.0fM | whitespace $%.0fM (of $%.0fM in-scope total)",
              coverage["assigned"] / 1e6, coverage["unassigned"] / 1e6, coverage["whitespace"] / 1e6,
              coverage["total_coi"] / 1e6)

    total_coi_all = account["coi_3yr_usd"].sum()
    whitespace_all_pct = account.loc[account["relationship"] == "Whitespace", "coi_3yr_usd"].sum() / total_coi_all

    # Pass 3 Section 4: site detail (monthly arrays + event ledger) for the
    # site drill-down modal, in-scope sites only. Read directly from the
    # S0-S17 pipeline's own per-site-month parquet - the same source
    # s11_explorer.py reads - rather than reimplemented, per Carlos's Part 6
    # caution against the cockpit's site view drifting from the explorer's.
    import ceo_cockpit_site_detail
    in_scope_site_names = set(sites.loc[sites["owner_entity"].isin(in_scope_owners), "site"])
    site_detail = ceo_cockpit_site_detail.load_site_detail(in_scope_site_names)
    log.info("site detail: %d sites, %d months (%s..%s), %d signature codes, %d gate codes",
              len(site_detail["per_site"]), len(site_detail["months"]), site_detail["months"][0],
              site_detail["months"][-1], len(site_detail["signature_lookup"]), len(site_detail["gate_lookup"]))

    from ceo_cockpit_payload import build_payload  # local import, defined below in this file's companion module
    payload = build_payload(sites, account, in_scope, plays, coverage, gtm, whitespace_all_pct, total_coi_all,
                             site_detail)

    with open("ceo_cockpit_template.html") as f:
        template = f.read()
    html = template.replace("__PAYLOAD_JSON__", json.dumps(payload, default=str, separators=(",", ":")))
    with open("ceo_cockpit.html", "w") as f:
        f.write(html)
    size_mb = len(html) / 1e6
    log.info("wrote ceo_cockpit.html (%.2f MB)%s", size_mb,
              " - EXCEEDS 25MB budget" if size_mb > 25 else "")
    log.info("S18 complete")


if __name__ == "__main__":
    main()
