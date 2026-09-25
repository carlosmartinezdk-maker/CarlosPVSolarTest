"""Part B - balance-of-plant risk index (BPRI), conviction tiers and customer targeting.

A PROPENSITY score, not a diagnosis: it says a plant has the profile of a plant with balance-of-plant problems,
never which pump. Components are scored 0-100 as percentiles within the peer group (class x size band x climate
region, falling back to class x size band, then class).

  C1  cooling_signal strength and trend (evidence; condensing plants only: CC, Gas Steam)
  C2  UNATTRIBUTED + BOP_INTERMITTENT share of the plant's HRI deficit (evidence)
  C3  starts per MW per year and cumulative starts (CEMS; proxy: CV of monthly LF + share of low-LF months)
  C4  trip rate per 1,000 operating hours (CEMS only)
  C5  ramp p95 / nameplate (CEMS only)
  C6  BoP age: years since ORIGINAL COD
  C7  interruptible gas exposure 1 - firm_delivery_share
Missing components are dropped and the remaining weights renormalised; without CEMS bpri_confidence = 'low'.
"""
import numpy as np
import pandas as pd
from config import X, OUT
from components import RECOVERY

W = {"C1": 0.30, "C2": 0.25, "C3": 0.15, "C4": 0.10, "C5": 0.05, "C6": 0.10, "C7": 0.05}
EVIDENCE = ["C1", "C2"]
EXPOSURE = ["C3", "C4", "C5", "C6", "C7"]
EVIDENCE_P = 75          # C1 / C2 >= p75
LIKELY_EXPOSURE = 60     # exposure composite >= p60
EXPOSED_EXPOSURE = 80    # exposure composite >= p80, no current evidence
PERSIST_YEARS = 2
MIN_PEERS = 5
HEAVY_PCTL = 75          # heavy cycling / trips: above class p75
ASOF_YEAR = 2025
MIN_FLEET_SHARE_RANK = 3  # customers with fewer gas sites are excluded from the share-at-risk ordering
EVIDENCE_TOP_N = 25
EVIDENCE_IMPUTE = 50      # neutral percentile when evidence is missing for lack of monthly data
GAS_FUELS_CEMS = ("Pipeline Natural Gas", "Natural Gas", "Other Gas", "Process Gas", "Other Gaseous Fuel")
COOL_GROUP = {"ON": "once-through", "OC": "once-through", "OT": "once-through", "RI": "recirculating",
              "RC": "recirculating", "RF": "recirculating", "RN": "recirculating", "DC": "dry", "HRI": "hybrid",
              "HT": "hybrid"}
SCOPE = {
    "CONFIRMED": "Condenser performance test + circulating-water flow verification + circ-water pump vibration survey",
    "LIKELY": "Diagnostic visit (heat-balance walkdown; condenser / cooling-water check if a summer penalty is present) - scope TBD",
    "EXPOSED": "Preventative: baseline vibration survey of BoP pumps (circ water, condensate, feedwater, lube oil) + monitoring plan",
    "LOW": "No action",
}
TIER_ORDER = ["CONFIRMED", "LIKELY", "EXPOSED", "LOW"]
HONESTY = [
    "The index detects a **system-level thermodynamic consequence** (a summer heat-rate penalty that survives ambient "
    "correction, consistent with condenser or cooling-water degradation), **not a component fault**. It never identifies a pump or bearing.",
    "Detection floor: **4.5% heat-rate change in a single month, 1.30% sustained over 12 months** (month-over-month noise "
    "sigma = 2.25% on stable baseload CC). Total failure of the largest auxiliary pump on a 500 MW plant is about 1.2% of "
    "output, so individual pumps sit below the floor by construction.",
    "Confirming a cause requires **on-site work**: a condenser performance test and a pump vibration survey.",
]


# ---------------------------------------------------------------------------------------------------------------
def cooling_types():
    d = pd.read_excel(X / "eia8602025" / "6_2_EnviroEquip_Y2025.xlsx", sheet_name="Cooling", header=1)
    d = d[pd.to_numeric(d["Plant Code"], errors="coerce").notna()]
    d["grp"] = d["Cooling Type 1"].astype(str).str.strip().map(COOL_GROUP).fillna("other")
    return d.groupby(d["Plant Code"].astype(int))["grp"].agg(lambda x: x.mode().iat[0]).to_dict()


def cems_plant_metrics(p):
    """Map CEMS gas units to the panel's plant x class and aggregate. Returns one row per plant x class."""
    import cems
    u = cems.load()
    if u.empty:
        return pd.DataFrame(columns=["plant_id", "cls"])
    u = u[u["primary_fuel"].isin(GAS_FUELS_CEMS) & (u["op_hours"] > 0)].copy()
    classes = p.groupby("plant_id")["cls"].agg(lambda x: set(x))
    ut = u["unit_type"].str.lower()

    def to_cls(pid, t):
        cs = classes.get(pid)
        if not cs:
            return None
        if len(cs) == 1:
            return next(iter(cs))
        if "combined cycle" in t and "CC" in cs:
            return "CC"
        if "combustion turbine" in t:
            return "GT" if "GT" in cs else ("CC" if "CC" in cs else None)
        if ("boiler" in t or "fired" in t or "stoker" in t or "cyclone" in t) and "ST" in cs:
            return "ST"
        if "internal combustion" in t and "IC" in cs:
            return "IC"
        return "CC" if "CC" in cs else None
    u["cls"] = [to_cls(pid, t) for pid, t in zip(u["plant_id"], ut)]
    u = u[u["cls"].notna()]
    u["ramp_frac"] = u["ramp_p95_mw"] / u["max_load_mw"].where(u["max_load_mw"] > 0)
    g = u.groupby(["plant_id", "cls"])
    m = pd.DataFrame({
        "cems_units": g["unit_id"].nunique(), "cems_years": g["year"].nunique(),
        "starts": g["starts"].sum(), "trips": g["trips"].sum(), "cold": g["cold"].sum(),
        "op_hours": g["op_hours"].sum(), "cems_heat_input": g["heat_input_mmbtu"].sum(),
        "ramp_p95": g.apply(lambda d: np.average(d["ramp_frac"].fillna(0), weights=d["max_load_mw"].clip(lower=1)),
                            include_groups=False)}).reset_index()
    m["starts_per_yr"] = m["starts"] / m["cems_years"]
    m["trip_rate"] = m["trips"] / m["op_hours"].where(m["op_hours"] > 0) * 1000
    m["cold_start_share"] = m["cold"] / m["starts"].where(m["starts"] > 0)
    # heat-input validation vs EIA-923 (same years): within +-5%?
    yrs = sorted(u["year"].unique())
    eia = p[p["year"].isin(yrs)].groupby(["plant_id", "cls"])["tot_mmbtu"].sum().rename("eia_mmbtu").reset_index()
    m = m.merge(eia, on=["plant_id", "cls"], how="left")
    m["heat_input_ratio"] = m["cems_heat_input"] / m["eia_mmbtu"].where(m["eia_mmbtu"] > 0)
    return m


def exposure_frame(p, cm):
    """plant x class exposure metrics (CEMS where available, proxies otherwise)."""
    last = p.sort_values("t_idx").groupby(["plant_id", "cls"]).last()
    base = last[["nameplate_mw", "unit_size_mw", "size_band", "climate_region", "chp_cohort"]].reset_index()
    first = p.groupby(["plant_id", "cls"])["first_op_year"].min().rename("original_cod")
    base = base.merge(first.reset_index(), on=["plant_id", "cls"], how="left")
    base["bop_age"] = ASOF_YEAR - base["original_cod"]
    op = p[(p["netgen"] > 0) & p["lf"].notna() & (p["lf"] <= 1.2)]
    prox = op.groupby(["plant_id", "cls"]).agg(lf_mean=("lf", "mean"), lf_std=("lf", "std"),
                                               low_lf_share=("lf", lambda x: ((x > 0) & (x < 0.15)).mean()))
    prox["lf_cv"] = prox["lf_std"] / prox["lf_mean"].where(prox["lf_mean"] > 0)
    base = base.merge(prox[["lf_cv", "low_lf_share"]].reset_index(), on=["plant_id", "cls"], how="left")
    fd = p.groupby(["plant_id", "cls"])["firm_delivery_share"].mean().rename("firm_delivery_mean")
    base = base.merge(fd.reset_index(), on=["plant_id", "cls"], how="left")
    base["interruptible"] = 1 - base["firm_delivery_mean"]
    base = base.merge(cm, on=["plant_id", "cls"], how="left")
    base["has_cems"] = base["cems_units"].fillna(0) > 0
    base["starts_per_MW_yr"] = base["starts_per_yr"] / base["nameplate_mw"].where(base["nameplate_mw"] > 0)
    base["cum_starts_est"] = base["starts_per_yr"] * base["bop_age"].clip(lower=1)
    return base


def heavy_cycling_set(ex):
    """(plant_id, cls) with elevated cycling or trip exposure: CEMS starts/MW/yr or trip rate above the class p75;
    without CEMS, LF coefficient of variation above the class p75 (proxy)."""
    ex = ex.copy()
    for c in ["starts_per_MW_yr", "trip_rate", "lf_cv"]:
        ex[c + "_p75"] = ex.groupby("cls")[c].transform(lambda x: np.nanpercentile(x, HEAVY_PCTL) if x.notna().sum() else np.nan)
    cems_heavy = ex["has_cems"] & ((ex["starts_per_MW_yr"] > ex["starts_per_MW_yr_p75"]) | (ex["trip_rate"] > ex["trip_rate_p75"]))
    proxy_heavy = ~ex["has_cems"] & (ex["lf_cv"] > ex["lf_cv_p75"])
    h = ex[cems_heavy | proxy_heavy]
    return set(zip(h["plant_id"], h["cls"]))


# ---------------------------------------------------------------------------------------------------------------
def _pctl(df, col, higher_is_worse=True):
    """Percentile 0-100 within class x size band x climate region; fall back to class x size band, then class."""
    out = pd.Series(np.nan, index=df.index)
    for keys in (["cls", "size_band", "climate_region"], ["cls", "size_band"], ["cls"]):
        g = df.groupby(keys)[col]
        n = g.transform("count")
        r = g.rank(pct=True) * 100
        use = out.isna() & (n >= MIN_PEERS) & df[col].notna()
        out[use] = r[use]
    return out if higher_is_worse else 100 - out


def evidence_frame(p, cs):
    """Plant-level and plant-year evidence: cooling signal strength/trend (C1) and unattributed+BoP deficit share (C2)."""
    s = p[p["scoreable"] & (p["resp_freq"] == "M") & p["hri_own"].notna()].copy()
    s["d"] = (1 - s["hri_own"]).clip(lower=0)
    s["ub"] = s["signature"].isin(["UNATTRIBUTED", "BOP_INTERMITTENT"])
    yr = s.groupby(["plant_id", "cls", "year"]).apply(
        lambda d: d.loc[d["ub"], "d"].sum() / d["d"].sum() if d["d"].sum() > 0 else 0.0, include_groups=False) \
        .rename("ub_share").reset_index()
    tot = s.groupby(["plant_id", "cls"]).apply(
        lambda d: d.loc[d["ub"], "d"].sum() / d["d"].sum() if d["d"].sum() > 0 else 0.0, include_groups=False) \
        .rename("ub_share").reset_index()
    c = cs.copy()
    recent = c[c["year"] >= ASOF_YEAR - 2].groupby(["plant_id", "cls"]).agg(
        cooling_signal=("cooling_signal", "mean"), cooling_trend=("cooling_trend", "first"),
        summer_penalty=("summer_residual", "mean"), cooling_years_flagged=("cooling_flag", "sum"))
    allf = c.groupby(["plant_id", "cls"])["cooling_flag"].sum().rename("cooling_flag_years")
    ev = tot.merge(recent.reset_index(), on=["plant_id", "cls"], how="left").merge(allf.reset_index(), on=["plant_id", "cls"], how="left")
    return ev, yr


def score(p, cs, cm):
    ex = exposure_frame(p, cm)
    ev, ev_year = evidence_frame(p, cs)
    d = ex.merge(ev, on=["plant_id", "cls"], how="left")
    cond = d["cls"].isin(["CC", "ST"])
    # C1: mean of strength and trend percentiles, condensing plants only
    d["c1_strength"] = np.where(cond, _pctl(d.assign(x=d["cooling_signal"].where(cond)), "x"), np.nan)
    d["c1_trend"] = np.where(cond, _pctl(d.assign(x=d["cooling_trend"].where(cond)), "x"), np.nan)
    d["C1"] = d[["c1_strength", "c1_trend"]].mean(axis=1, skipna=True)
    d["C2"] = _pctl(d, "ub_share")
    # C1 is structurally absent for GT / IC (no condenser): those weights are renormalised away. Evidence missing for
    # lack of data (annual respondents, too few seasonal months) is imputed at the peer median, so a plant without
    # monthly evidence cannot rank on exposure alone; flagged.
    d["evidence_imputed"] = (cond & d["C1"].isna()) | d["C2"].isna()
    d.loc[cond & d["C1"].isna(), "C1"] = EVIDENCE_IMPUTE
    d["C2"] = d["C2"].fillna(EVIDENCE_IMPUTE)
    c3c = pd.concat([_pctl(d.assign(x=d["starts_per_MW_yr"].where(d["has_cems"])), "x"),
                     _pctl(d.assign(x=d["cum_starts_est"].where(d["has_cems"])), "x")], axis=1).mean(axis=1)
    c3p = pd.concat([_pctl(d, "lf_cv"), _pctl(d, "low_lf_share")], axis=1).mean(axis=1)
    d["C3"] = np.where(d["has_cems"], c3c, c3p)
    d["C4"] = np.where(d["has_cems"], _pctl(d.assign(x=d["trip_rate"].where(d["has_cems"])), "x"), np.nan)
    d["C5"] = np.where(d["has_cems"], _pctl(d.assign(x=d["ramp_p95"].where(d["has_cems"])), "x"), np.nan)
    d["C6"] = _pctl(d, "bop_age")
    d["C7"] = _pctl(d, "interruptible")

    def wmean(row, comps):
        ws = {c: W[c] for c in comps if pd.notna(row[c])}
        return sum(row[c] * w for c, w in ws.items()) / sum(ws.values()) if ws else np.nan
    d["BPRI"] = d.apply(lambda r: wmean(r, W), axis=1)
    d["exposure_composite"] = d.apply(lambda r: wmean(r, EXPOSURE), axis=1)
    d["bpri_confidence"] = np.where(d["has_cems"], "high", "low")
    d["c3_source"] = np.where(d["has_cems"], "CEMS", "proxy (LF variance)")
    # persistence of evidence (years)
    ev_year = ev_year.merge(d[["plant_id", "cls", "size_band", "climate_region"]], on=["plant_id", "cls"], how="left")
    ev_year["c2_year"] = ev_year.groupby("year", group_keys=False).apply(lambda g: _pctl(g, "ub_share"), include_groups=False)
    c2p = ev_year[ev_year["c2_year"] >= EVIDENCE_P].groupby(["plant_id", "cls"]).size().rename("c2_years")
    d = d.merge(c2p.reset_index(), on=["plant_id", "cls"], how="left")
    d["c2_years"] = d["c2_years"].fillna(0)
    d["cooling_flag_years"] = d["cooling_flag_years"].fillna(0)
    d["tier"] = assign_tier(d["C1"], d["C2"], d["exposure_composite"],
                            (d["cooling_flag_years"] >= PERSIST_YEARS) | (d["c2_years"] >= PERSIST_YEARS))
    d["suggested_scope"] = d["tier"].map(SCOPE)
    d.loc[(d["tier"] == "LIKELY") & ~d["cls"].isin(["CC", "ST"]),
          "suggested_scope"] = "Diagnostic visit (heat-balance walkdown, fuel-gas and lube-oil systems) - scope TBD"
    d["evidence_led"] = (d["C1"] >= EVIDENCE_P) | (d["C2"] >= EVIDENCE_P)
    d["exposure_led"] = ~d["evidence_led"] & (d["exposure_composite"] >= EXPOSED_EXPOSURE)
    return d, ev_year


def assign_tier(c1, c2, expo, persistent):
    c1 = pd.Series(c1).fillna(-1)
    c2 = pd.Series(c2).fillna(-1)
    expo = pd.Series(expo).fillna(-1)
    conf = (c1 >= EVIDENCE_P) & (c2 >= EVIDENCE_P) & persistent
    lik = ((c1 >= EVIDENCE_P) | (c2 >= EVIDENCE_P)) & (expo >= LIKELY_EXPOSURE)
    expd = (expo >= EXPOSED_EXPOSURE) & (c1 < EVIDENCE_P) & (c2 < EVIDENCE_P)
    return np.select([conf, lik, expd], ["CONFIRMED", "LIKELY", "EXPOSED"], default="LOW")


def yearly_tiers(d, cs, ev_year):
    """Tier per plant-year (for 'capacity by tier over time'): year's C1 (cooling signal vs peers that year), year's C2,
    static exposure; persistence = that year and the previous year both carry evidence."""
    y = ev_year[["plant_id", "cls", "year", "c2_year"]].merge(
        cs[["plant_id", "cls", "year", "cooling_signal", "cooling_flag"]], on=["plant_id", "cls", "year"], how="outer")
    y = y.merge(d[["plant_id", "cls", "size_band", "climate_region", "exposure_composite"]], on=["plant_id", "cls"], how="left")
    cond = y["cls"].isin(["CC", "ST"])
    y["c1_year"] = y.groupby("year", group_keys=False).apply(
        lambda g: _pctl(g.assign(x=g["cooling_signal"].where(g["cls"].isin(["CC", "ST"]))), "x"), include_groups=False)
    y.loc[~cond, "c1_year"] = np.nan
    y = y.sort_values(["plant_id", "cls", "year"])
    ev = ((y["c1_year"] >= EVIDENCE_P) | (y["c2_year"] >= EVIDENCE_P)).astype(int)
    prev = ev.groupby([y["plant_id"], y["cls"]]).shift(1).fillna(0)
    y["tier"] = assign_tier(y["c1_year"], y["c2_year"], y["exposure_composite"], (ev + prev) >= 2)
    return y[["plant_id", "cls", "year", "tier", "c1_year", "c2_year"]]


# ---------------------------------------------------------------------------------------------------------------
def recoverable(p):
    tmax = p["t_idx"].max()
    s = p[(p["t_idx"] > tmax - 24) & p["signature"].isin(["COOLING_DEGRADATION", "BOP_INTERMITTENT"])]
    return (s.groupby(["plant_id", "cls"])["recoverable_usd"].sum() / 2).rename("recoverable_usd").reset_index()


def site_targets(p, d, summ):
    last = p.sort_values("t_idx").groupby(["plant_id", "cls"]).last()[["plant_name", "state", "ba"]].reset_index()
    t = d.merge(last, on=["plant_id", "cls"], how="left").merge(recoverable(p), on=["plant_id", "cls"], how="left")
    t["recoverable_usd"] = t["recoverable_usd"].fillna(0)
    t = t.merge(summ[["plant_id", "cls", "customer_group", "ssi_prospect", "dominant_component"]], on=["plant_id", "cls"], how="left")
    t["is_ssi_customer"] = t["ssi_prospect"] == "SSI customer"
    # measured summer penalty = summer minus shoulder HRI gap (recent 3-yr mean); summer_gap_to_envelope = raw summer 1-HRI
    t["summer_penalty_pct"] = t["cooling_signal"] * 100
    t["summer_gap_to_envelope_pct"] = t["summer_penalty"] * 100
    t["cooling_signal_pct"] = t["cooling_signal"] * 100
    t["cooling_trend_pct_per_yr"] = t["cooling_trend"] * 100
    t = t.rename(columns={"customer_group": "customer", "cls": "tech", "nameplate_mw": "mw", "dominant_component": "dominant_signature"})
    cols = ["plant_id", "plant_name", "customer", "is_ssi_customer", "state", "ba", "tech", "mw", "original_cod", "bop_age",
            "C1", "C2", "C3", "C4", "C5", "C6", "C7", "BPRI", "bpri_confidence", "tier", "exposure_composite",
            "evidence_led", "exposure_led", "evidence_imputed", "cooling_signal_pct", "cooling_trend_pct_per_yr", "summer_penalty_pct", "summer_gap_to_envelope_pct",
            "cooling_flag_years", "c2_years", "starts_per_MW_yr", "cum_starts_est", "trip_rate", "cold_start_share",
            "ramp_p95", "lf_cv", "low_lf_share", "interruptible", "c3_source", "has_cems", "heat_input_ratio",
            "recoverable_usd", "dominant_signature", "suggested_scope", "chp_cohort", "climate_region", "size_band"]
    t = t[cols].sort_values(["BPRI"], ascending=False)
    return t


def customer_targets(t):
    g = t.groupby("customer")

    def worst(x):
        return x.loc[x["BPRI"].idxmax(), "plant_name"] if x["BPRI"].notna().any() else ""
    c = pd.DataFrame({
        "is_ssi_customer": g["is_ssi_customer"].any(),
        "sites_total": g.size(),
        "total_gas_mw": g["mw"].sum(),
        "sites_confirmed": g["tier"].apply(lambda x: (x == "CONFIRMED").sum()),
        "sites_likely": g["tier"].apply(lambda x: (x == "LIKELY").sum()),
        "sites_exposed": g["tier"].apply(lambda x: (x == "EXPOSED").sum()),
        "mw_at_risk": g.apply(lambda x: x.loc[x["tier"].isin(["CONFIRMED", "LIKELY"]), "mw"].sum(), include_groups=False),
        "bpri_weighted": g.apply(lambda x: np.average(x["BPRI"].fillna(0), weights=x["mw"].fillna(0).clip(lower=0.1)), include_groups=False),
        "recoverable_usd": g["recoverable_usd"].sum(),
        "worst_site": g.apply(worst, include_groups=False),
        "states": g["state"].agg(lambda x: ", ".join(sorted(set(map(str, x))))),
        "bas": g["ba"].agg(lambda x: ", ".join(sorted(set(map(str, x))))),
        "cems_backed_sites": g["has_cems"].sum(),
    }).reset_index()
    c["share_at_risk"] = c["mw_at_risk"] / c["total_gas_mw"].where(c["total_gas_mw"] > 0)
    c["rank_recoverable"] = c["recoverable_usd"].rank(ascending=False, method="min").astype(int)
    elig = c["sites_total"] >= MIN_FLEET_SHARE_RANK
    c["rank_share_at_risk"] = np.nan
    c.loc[elig, "rank_share_at_risk"] = c.loc[elig, "share_at_risk"].rank(ascending=False, method="min")
    c["share_rank_note"] = np.where(elig, "", f"fewer than {MIN_FLEET_SHARE_RANK} gas sites - excluded from share-at-risk ordering")
    return c.sort_values("recoverable_usd", ascending=False)


# ---------------------------------------------------------------------------------------------------------------
def evidence_pack(p, t, cs, outdir):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    outdir.mkdir(parents=True, exist_ok=True)
    for f in outdir.glob("*"):
        f.unlink()
    top = t[t["tier"] == "CONFIRMED"].sort_values("BPRI", ascending=False).head(EVIDENCE_TOP_N)
    index = []
    for _, r in top.iterrows():
        pid, cls = r["plant_id"], r["tech"]
        d = p[(p["plant_id"] == pid) & (p["cls"] == cls) & p["scoreable"]].sort_values("t_idx")
        c = cs[(cs["plant_id"] == pid) & (cs["cls"] == cls)].sort_values("year")
        fig, ax = plt.subplots(1, 2, figsize=(12, 3.6), gridspec_kw={"width_ratios": [2.2, 1]})
        x = pd.to_datetime(dict(year=d["year"], month=d["month"], day=15))
        ax[0].plot(x, d["hri"], color="#1d4e6f", lw=1.5, marker="o", ms=2.5)
        su = d["month"].isin([6, 7, 8, 9])
        ax[0].scatter(x[su], d.loc[su, "hri"], color="#c47f45", s=16, zorder=3, label="Jun-Sep")
        ax[0].set_title("Monthly HRI (load- and ambient-corrected; summer highlighted)", fontsize=10)
        ax[0].grid(alpha=.3); ax[0].legend(fontsize=8, frameon=False)
        ax[1].bar(c["year"].astype(str), c["cooling_signal"] * 100, color=np.where(c["cooling_flag"], "#b0452f", "#b9b5b1"))
        ax[1].plot(c["year"].astype(str), c["peer_p75"] * 100, color="#1d4e6f", marker="_", ms=14, lw=0, label="peer p75")
        ax[1].axhline(1.5, color="#6b6b6b", ls=":", lw=1)
        ax[1].set_title("Cooling signal: summer minus shoulder penalty (pts)", fontsize=10)
        ax[1].legend(fontsize=8, frameon=False); ax[1].grid(alpha=.3, axis="y")
        fig.tight_layout()
        png = f"{pid}_{cls}.png"
        fig.savefig(outdir / png, dpi=120); plt.close(fig)
        yr_rows = "\n".join(f"| {int(y)} | {s*100:.2f} | {q*100:.2f} | {'yes' if fl else 'no'} |"
                            for y, s, q, fl in zip(c["year"], c["cooling_signal"], c["peer_p75"], c["cooling_flag"]))
        fmt = lambda v, f="{:.0f}": "n/a" if pd.isna(v) else f.format(v)
        rec_line = (f"**Indicative recoverable fuel cost (cooling + BoP signatures, last 24 months annualised):** ${r['recoverable_usd']:,.0f}/yr "
                    "- an UNVALIDATED placeholder recovery fraction applied to fuel priced at the plant's gas cost; not a quote."
                    if r["recoverable_usd"] > 0 else
                    "**Indicative recoverable fuel cost:** none attributed in the last 24 months - recent summer months are already "
                    "explained by compressor fouling or duct firing, or the cooling signal is below the flag threshold. The "
                    "tier rests on the multi-year evidence above.")
        md = f"""# {r['plant_name']} ({cls}) - balance-of-plant evidence brief

**Customer:** {r['customer']} ({'SSI customer' if r['is_ssi_customer'] else 'prospect'}) · **State / BA:** {r['state']} / {r['ba']} · **Capacity:** {r['mw']:,.0f} MW · **Original COD:** {fmt(r['original_cod'])} (BoP age {fmt(r['bop_age'])} yrs)

**Tier: CONFIRMED** · BPRI {r['BPRI']:.0f} / 100 · confidence **{r['bpri_confidence']}**{' (no CEMS: cycling and trip exposure are monthly proxies)' if r['bpri_confidence'] == 'low' else ''}

![HRI series and cooling signal]({png})

## What the data shows
- **Summer heat-rate penalty surviving ambient correction:** recent cooling signal {fmt(r['cooling_signal_pct'], '{:.2f}')} points (summer minus shoulder), trend {fmt(r['cooling_trend_pct_per_yr'], '{:+.2f}')} pts/yr; flagged in {int(r['cooling_flag_years'])} year(s).
- **Unexplained / intermittent deficit:** C2 percentile {fmt(r['C2'])} (share of the HRI deficit not explained by fouling, hot-gas-path, duct firing or fuel quality).

| Year | Cooling signal (pts) | Peer p75 (pts) | Flagged |
|---|---|---|---|
{yr_rows}

## Peer comparison and exposure profile
Percentiles vs peers (same class, unit-size band, climate region):
C1 cooling {fmt(r['C1'])} · C2 unattributed/BoP {fmt(r['C2'])} · C3 cycling {fmt(r['C3'])} ({r['c3_source']}) · C4 trips {fmt(r['C4'])} · C5 ramping {fmt(r['C5'])} · C6 BoP age {fmt(r['C6'])} · C7 interruptible gas {fmt(r['C7'])}.
Starts/MW/yr {fmt(r['starts_per_MW_yr'], '{:.2f}')} · trip rate {fmt(r['trip_rate'], '{:.2f}')} per 1,000 h · cold-start share {fmt(r['cold_start_share'], '{:.0%}')}.

{rec_line}

## Suggested scope
{r['suggested_scope']}. The circulating-water pump vibration survey should read 1x / 2x / broadband / vane-pass-frequency signatures.

## What this brief does not claim
""" + "\n".join(f"- {h}" for h in HONESTY) + "\n"
        (outdir / f"{pid}_{cls}.md").write_text(md, encoding="utf-8")
        index.append(f"| {r['plant_name']} | {cls} | {r['customer']} | {r['BPRI']:.0f} | [{pid}_{cls}.md]({pid}_{cls}.md) |")
    (outdir / "README.md").write_text("# BoP evidence pack - top CONFIRMED sites by BPRI\n\n| Plant | Class | Customer | BPRI | Brief |\n|---|---|---|---|---|\n"
                                      + "\n".join(index) + "\n\n" + "\n".join(f"- {h}" for h in HONESTY) + "\n", encoding="utf-8")
    return len(top)


def write_customer_targets(c, path):
    """Both orderings, split by SSI customer vs prospect, in one long table:
    ordering = 'by_recoverable_usd' (the biggest prize) or 'by_share_at_risk' (the most systemic; >= MIN_FLEET_SHARE_RANK sites)."""
    out = []
    for seg, cc in c.groupby(np.where(c["is_ssi_customer"], "SSI customer (cross-sell)", "prospect (cold outreach)")):
        a = cc.sort_values("recoverable_usd", ascending=False).assign(ordering="by_recoverable_usd", segment=seg)
        b = cc[cc["sites_total"] >= MIN_FLEET_SHARE_RANK].sort_values(["share_at_risk", "mw_at_risk"], ascending=False) \
            .assign(ordering="by_share_at_risk", segment=seg)
        for x in (a, b):
            x["rank_in_segment"] = np.arange(1, len(x) + 1)
            out.append(x)
    o = pd.concat(out, ignore_index=True)
    front = ["ordering", "segment", "rank_in_segment", "customer", "is_ssi_customer"]
    o = o[front + [k for k in o.columns if k not in front]]
    o.to_csv(path, index=False)
    return o


# ---------------------------------------------------------------------------------------------------------------
NOISE_LF_MIN = 0.60     # stable baseload: LF >= 0.6 in both months
NOISE_DLF_MAX = 0.10    # and |dLF| <= 0.10


def hr_noise(p):
    """Month-over-month HR noise (sigma of % change) on stable baseload CC, monthly respondents, non-CHP."""
    d = p[(p["cls"] == "CC") & p["scoreable"] & (p["resp_freq"] == "M") & ~p["chp_cohort"]].sort_values(["plant_id", "t_idx"])
    g = d.groupby("plant_id")
    ok = (d["t_idx"] - g["t_idx"].shift(1) == 1) & (d["lf"] >= NOISE_LF_MIN) & (g["lf"].shift(1) >= NOISE_LF_MIN) \
        & ((d["lf"] - g["lf"].shift(1)).abs() <= NOISE_DLF_MAX)
    r = (d["hr"] / g["hr"].shift(1) - 1)[ok]
    return float(r.std()), float(1.4826 * (r - r.median()).abs().median()), int(len(r))


def gates(p, cs, cm, t):
    rows = []
    sd, rob, n = hr_noise(p)
    rows.append({"check": "Month-over-month HR noise, stable baseload CC (sigma)", "expected": "2.25% +-0.4",
                 "got": f"{sd*100:.2f}%", "status": "PASS" if abs(sd * 100 - 2.25) <= 0.4 else "WARN",
                 "note": f"n={n} month pairs, LF>={NOISE_LF_MIN} both months, |dLF|<={NOISE_DLF_MAX}; robust sigma (1.4826 MAD) "
                         f"{rob*100:.2f}% - heavy tails. Implied floors: 2 sigma = {2*sd*100:.1f}% single month, "
                         f"{2*sd/np.sqrt(12)*100:.2f}% over 12"})
    cc = cs[cs["cls"] == "CC"]
    yl = int(cc["year"].max())
    prev = cc[cc["year"] == yl].groupby("plant_id")["cooling_flag"].any().mean()
    ever = cc.groupby("plant_id")["cooling_flag"].any().mean()
    rows.append({"check": f"COOLING_DEGRADATION prevalence, CC plants ({yl})", "expected": "5-20% of CC plants",
                 "got": f"{prev:.1%}", "status": "PASS" if 0.05 <= prev <= 0.20 else "WARN",
                 "note": f"point prevalence in the latest year; {ever:.1%} of CC plants flagged in at least one year 2019-{yl}"})
    conf = (t["tier"] == "CONFIRMED").mean()
    conf_mw = t.loc[t["tier"] == "CONFIRMED", "mw"].sum() / t["mw"].sum()
    rows.append({"check": "CONFIRMED tier share of gas fleet", "expected": "<10%", "got": f"{conf:.1%} of sites",
                 "status": "PASS" if conf < 0.10 else "FAIL",
                 "note": f"{conf_mw:.1%} of capacity; tiers {t['tier'].value_counts().to_dict()}"})
    rows.append({"check": "BoP tier counts sum to site count", "expected": "equal", "got": f"{t['tier'].isin(TIER_ORDER).sum()} / {len(t)}",
                 "status": "PASS" if t["tier"].isin(TIER_ORDER).sum() == len(t) else "FAIL", "note": ""})
    if len(cm):
        r = cm["heat_input_ratio"].dropna()
        within = ((r - 1).abs() <= 0.05).mean()
        cov = t["has_cems"].mean()
        cov_mw = t.loc[t["has_cems"], "mw"].sum() / t["mw"].sum()
        rows.append({"check": "CEMS heat input vs EIA-923 (plant x class, same years)", "expected": "within +-5%",
                     "got": f"median ratio {r.median():.3f}; {within:.0%} within +-5%",
                     "status": "PASS" if abs(r.median() - 1) <= 0.05 else "WARN",
                     "note": f"CEMS-backed sites {cov:.0%} ({cov_mw:.0%} of capacity); mismatches are EPA stack vs EIA "
                             "generator mapping, partial CEMS coverage (<25 MW units) and duct/aux boilers"})
    return rows
