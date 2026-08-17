"""
Pass 3 site-detail extraction (CEO_COCKPIT_REVISIONS_PASS3.md Section 4).

Reads the S0-S17 pipeline's per-site-month parquet (data/site_month_dollars.parquet
- the same source s11_explorer.py reads for explorer.html) and the event
ledger (data/event_ledger.parquet) DIRECTLY, rather than re-deriving or
re-scraping explorer.html's built payload. This is deliberate: Carlos's
Part 6 caution in the Pass 3 spec is that the cockpit's site view must be
"generated from the same functions" as the explorer, not reimplemented -
reading the identical upstream parquet the explorer reads is the way to
guarantee that, rather than a second computation that can drift.

In-scope only (~2,411 of 6,203 sites) to protect the payload budget.
"""
import pandas as pd

MONTHLY_SRC = "data/site_month_dollars.parquet"
LEDGER_SRC = "data/event_ledger.parquet"

# All 6,203 sites share one identical 89-month calendar grid (2019-01
# through the latest month with weather data) - verified directly against
# the source parquet, not assumed. Storing `months` once at the payload
# top level instead of once per site is the single biggest saving here.
MONTHLY_COLS = ["site", "month_start", "E_act_mwh", "E_exp_mwh", "PI", "PRI", "D",
                "signature_final", "gate_fired", "benchmark_mode", "block_fraction",
                "peer_count", "peer_radius_km", "peers_healthy"]


def _rnd(v, nd):
    return None if pd.isna(v) else round(float(v), nd)


def _rnd_fraction(v, nd):
    """block_fraction stores discrete values as fraction strings ("1/6",
    from config.BLOCK_FRACTION_TABLE) mixed with plain floats/NaN in the
    same column - normalise both to a rounded float."""
    if pd.isna(v):
        return None
    if isinstance(v, str) and "/" in v:
        num, den = v.split("/")
        return round(float(num) / float(den), nd)
    return round(float(v), nd)


def _rndint(v):
    return None if pd.isna(v) else int(round(float(v)))


def load_site_detail(in_scope_sites: set) -> dict:
    """Returns dict(months, signature_lookup, gate_lookup, per_site) where
    per_site[site] holds parallel per-month arrays (aligned to `months`)
    plus flat per-site ledger arrays (one entry per site-year-signature
    row). Values are pre-rounded (PI/PRI/D to 3dp, MWh to whole numbers)
    and signature/gate are small-int indices into the two lookup lists -
    per the spec's "signature-as-index alone saves most of it.\""""
    df = pd.read_parquet(MONTHLY_SRC, columns=MONTHLY_COLS)
    df = df[df["site"].isin(in_scope_sites)].copy()
    df["month_start"] = pd.to_datetime(df["month_start"])

    months = sorted(df["month_start"].unique())
    month_labels = [pd.Timestamp(m).strftime("%Y-%m") for m in months]

    sig_values = sorted(df["signature_final"].dropna().unique().tolist())
    gate_values = sorted(df["gate_fired"].dropna().unique().tolist())
    sig_index = {v: i for i, v in enumerate(sig_values)}
    gate_index = {v: i for i, v in enumerate(gate_values)}

    per_site = {}
    for site, g in df.groupby("site", sort=False):
        # reindex onto the shared month grid so every site's arrays line
        # up positionally with `months`, even though every site already
        # has all 89 rows in practice - cheap insurance against a future
        # dataset where that stops being true.
        g = g.set_index("month_start").reindex(months)
        per_site[site] = dict(
            e_act=[_rndint(v) for v in g["E_act_mwh"]],
            e_exp=[_rndint(v) for v in g["E_exp_mwh"]],
            d=[_rnd(v, 3) for v in g["D"]],
            sig_idx=[sig_index.get(v) for v in g["signature_final"]],
            gate_idx=[gate_index.get(v) for v in g["gate_fired"]],
            benchmark_peer=[None if pd.isna(v) else int(v == "peer") for v in g["benchmark_mode"]],
            block_fraction=[_rnd_fraction(v, 3) for v in g["block_fraction"]],
            peer_count=[_rndint(v) for v in g["peer_count"]],
            peer_radius_km=[_rnd(v, 1) for v in g["peer_radius_km"]],
            peers_healthy=[_rndint(v) for v in g["peers_healthy"]],
            ledger_year=[], ledger_sig_idx=[], ledger_months=[], ledger_episodes=[],
            ledger_exposure_months=[], ledger_mwh_lost=[], ledger_usd_lost=[],
        )

    ledger = pd.read_parquet(LEDGER_SRC)
    ledger = ledger[ledger["site"].isin(in_scope_sites)].sort_values(["site", "year"])
    for site, g in ledger.groupby("site", sort=False):
        d = per_site.setdefault(site, {})
        d["ledger_year"] = g["year"].astype(int).tolist()
        d["ledger_sig_idx"] = [sig_index.get(v) for v in g["signature"]]
        d["ledger_months"] = g["months"].astype(int).tolist()
        d["ledger_episodes"] = [_rndint(v) for v in g["episodes"]]
        d["ledger_exposure_months"] = [_rnd(v, 1) for v in g["exposure_months"]]
        d["ledger_mwh_lost"] = [_rndint(v) for v in g["mwh_lost"]]
        d["ledger_usd_lost"] = [_rndint(v) for v in g["usd_lost"]]

    return dict(months=month_labels, signature_lookup=sig_values,
                gate_lookup=gate_values, per_site=per_site)
