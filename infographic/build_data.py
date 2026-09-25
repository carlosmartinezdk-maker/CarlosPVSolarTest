"""Build the compact DATA payloads for the results infographics (gas and BESS) from the analysis outputs.

Conviction classes (per site, over scored monthly-resolved months, deficit = gas HRI_own < 0.95 /
BESS a technical fault signature):
  New        deficit months only in the last 12 months (>= 2 of them)
  Chronic    deficit in >= 50% of all scored months and >= 50% of the last 12
  Improving  deficit share in the first half >= 30% and the last-12 share at least 25 pts lower
  Event      any other site with deficit months
  None       no deficit months
"""
import json
import sys
import numpy as np
import pandas as pd
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
YEARS = list(range(2019, 2026))
CONV = ["None", "Chronic", "Event", "New", "Improving"]


def r3(x):
    return None if x is None or not np.isfinite(x) else round(float(x), 3)


def rint(x):
    return 0 if x is None or not np.isfinite(x) else int(round(float(x)))


def conviction(t, flag, scored):
    """t: t_idx array, flag: deficit bool, scored: bool."""
    t, flag = t[scored], flag[scored]
    if len(t) == 0 or not flag.any():
        return "None"
    tmax = t.max()
    last = t > tmax - 12
    if flag[~last].sum() == 0 and flag[last].sum() >= 2:
        return "New"
    share, share12 = flag.mean(), flag[last].mean() if last.any() else 0
    if share >= 0.5 and share12 >= 0.5:
        return "Chronic"
    half = t <= np.median(t)
    if flag[half].mean() >= 0.3 and share12 <= flag[half].mean() - 0.25:
        return "Improving"
    return "Event"


def _idx(values):
    u = sorted(set(values))
    return u, {v: i for i, v in enumerate(u)}


def gas():
    G = REPO / "gas_analysis"
    m = pd.read_parquet(G / "outputs" / "gas_monthly.parquet")
    summ = pd.read_excel(G / "outputs" / "gas_plant_summary.xlsx", sheet_name="plant_summary")
    pl = pd.read_parquet(G / "data" / "cache" / "eia860_plants.parquet")[["plant_id", "lat", "lon", "ba_860"]]
    tech_code = ["CC", "GT", "ST", "IC"]
    tech = ["Combined Cycle", "Gas Turbine", "Gas Steam", "Gas Recip"]
    sigs = ["FOULING", "HGP", "NONRECOVERABLE", "CYCLING", "UNATTRIBUTED", "ANNUAL_ONLY", "DUCT_FIRING",
            "FUEL_QUALITY", "HEALTHY"]
    sig_i = {s: i for i, s in enumerate(sigs)}
    keep = m.groupby(["plant_id", "tech_class"])["scoreable"].transform("any")
    m = m[keep].copy()
    m["t_idx"] = m["year"] * 12 + m["month"] - 1
    summ = summ.merge(pl, on="plant_id", how="left")
    summ["owner"] = summ["customer_group"].fillna(summ["owner"]).fillna(summ["operator"]).fillna("Unknown")
    s_keys = set(zip(m["plant_id"], m["tech_class"]))
    summ = summ[[k in s_keys for k in zip(summ["plant_id"], summ["cls"])]]
    cap = m.groupby(["plant_id", "tech_class"])["Nameplate_MW"].max()
    summ["cap"] = [cap.get((a, b), 0) for a, b in zip(summ["plant_id"], summ["cls"])]
    cust_cap = summ.groupby("owner")["cap"].sum().sort_values(ascending=False)
    custs = list(cust_cap.index)
    c_i = {c: i for i, c in enumerate(custs)}
    states, s_i = _idx(summ["state"].fillna("NA"))
    tier = {"plant": 0, "state": 1, "state_fill": 1, "national": 2, "national_fill": 2}
    sites = []
    grp = {k: d for k, d in m.groupby(["plant_id", "tech_class"])}
    for _, r in summ.iterrows():
        d = grp[(r["plant_id"], r["cls"])].sort_values("t_idx")
        flag = (d["HRI_own"] < 0.95).to_numpy() & d["scoreable"].to_numpy()
        scored = (d["scoreable"] & (d["respondent_freq"] == "M")).to_numpy()
        if not scored.any():
            scored = d["scoreable"].to_numpy()
        y = {}
        for yr, dy in d.groupby("year"):
            arr = {k: [None] * 12 for k in ["i", "v", "r", "m", "g"]}
            for _, q in dy.iterrows():
                k = int(q["month"]) - 1
                sc = bool(q["scoreable"])
                arr["i"][k] = r3(q["HRI"]) if sc else None
                arr["v"][k] = rint(q["Waste_USD"]) if sc else 0
                arr["r"][k] = rint(q["Recoverable_USD"]) if sc else 0
                arr["m"][k] = rint(q["Excess_MMBtu"]) if sc else 0
                arr["g"][k] = sig_i.get(q["signature"], -1) if sc else -1
            ng, mm = dy["Netgen_MWh"].clip(lower=0).sum(), dy["Elec_MMBtu"].clip(lower=0).sum()
            ok = dy[dy["scoreable"]]
            hr = ok["Elec_MMBtu"].sum() * 1000 / ok["Netgen_MWh"].sum() if ok["Netgen_MWh"].sum() > 0 else None
            mw = float(dy["Nameplate_MW"].max()) if dy["Nameplate_MW"].notna().any() else 0.0
            y[str(yr)] = {"mw": round(mw, 1), "h": rint(hr) if hr else None,
                          "lf": r3(ng / (mw * dy["month"].map(lambda mo: pd.Period(f"{yr}-{mo}").days_in_month * 24).sum())) if mw > 0 else None,
                          "p": r3(ok["PRI"].median()) if ok["PRI"].notna().any() else None, **arr}
        dom = r["dominant_component"] if isinstance(r["dominant_component"], str) else "HEALTHY"
        sites.append({
            "n": r["plant_name"], "id": int(r["plant_id"]), "t": tech_code.index(r["cls"]), "c": c_i[r["owner"]],
            "s": s_i[r["state"] if isinstance(r["state"], str) else "NA"], "ssi": int(r["ssi_prospect"] == "SSI customer"),
            "mw": round(float(r["cap"]), 1),
            "la": r3(r["lat"]), "lo": r3(r["lon"]), "oy": rint(r["cod_year"]) if pd.notna(r["cod_year"]) else None,
            "ba": r["ba"] if isinstance(r["ba"], str) else "",
            "cv": CONV.index(conviction(d["t_idx"].to_numpy(), flag, scored)),
            "rc": rint(r["recoverable_usd_per_yr"]) if pd.notna(r["recoverable_usd_per_yr"]) else 0,
            "pb": r3(r["payback_yr"]) if pd.notna(r["payback_yr"]) else None,
            "tr": r3(r["hri_own_slope_pct_per_yr"]) if pd.notna(r["hri_own_slope_pct_per_yr"]) else None,
            "ew": rint(r["eoh_since_wash"]) if pd.notna(r["eoh_since_wash"]) else None,
            "ws": r["wash_status"] if isinstance(r["wash_status"], str) else "",
            "dm": sig_i.get(dom, sig_i["HEALTHY"]), "ct": tier.get(r["cost_source_main"], 2),
            "tier": r["conviction_tier"] if isinstance(r["conviction_tier"], str) else "-",
            "x": {"u": r3(r["unit_size_mw"]), "nu": rint(r["n_units"]) if pd.notna(r["n_units"]) else None,
                  "db": 1 if r["duct_burners"] == "Y" else 0, "chp": 1 if bool(r["chp_cohort"]) else 0,
                  "fd": r3(d["firm_delivery_share"].mean()) if d["firm_delivery_share"].notna().any() else None},
            "y": y})
    capf = pd.read_parquet(G / "data" / "cache" / "eia860_gas_capacity.parquet")
    fleet = {str(i): [round(float(capf[(capf["cls"] == c) & (capf["year"] == y)]["nameplate_mw"].sum()), 1) for y in YEARS]
             for i, c in enumerate(tech_code)}
    data = {"kind": "gas", "fleetCap": fleet, "tech": tech, "states": states, "custs": custs, "sigs": sigs, "conv": CONV,
            "years": YEARS, "sites": sites}
    sc = m[m["scoreable"]]
    expect = {"recoverable_usd_total": float(sc["Recoverable_USD"].sum()), "waste_usd_total": float(sc["Waste_USD"].sum()),
              "excess_mmbtu_total": float(sc["Excess_MMBtu"].sum()),
              "cc_median_hr_2025_spec": 7307, "cap_2025_gw": {"CC": 333, "GT": 160}}
    return data, expect


def bess():
    B = REPO / "bess_analysis"
    sys.path.insert(0, str(B))
    m = pd.read_parquet(B / "outputs" / "bess_monthly.parquet")
    summ = pd.read_excel(B / "outputs" / "bess_site_summary.xlsx", sheet_name="site_summary")
    pl = pd.read_parquet(B / "data" / "cache" / "eia860_plants_bess.parquet")[["plant_id", "lat", "lon"]]
    # rolling 12-month eta refits (time-varying eta for the efficiency line)
    import panel, peers, efficiency_decomp as E
    p = peers.add_uti(panel.build())
    dec, rolls = E.decompose(p)
    roll = {(int(a), int(b)): c for a, b, c in zip(rolls["plant_id"], rolls["t_end"], rolls["eta"])}
    tech = ["<1.5h", "1.5-2.5h", "2.5-4.5h", ">4.5h"]
    sigs = ["FULL_OUTAGE", "PARTIAL_AVAILABILITY", "THERMAL_AUX", "UNATTRIBUTED", "CELL_DEGRADATION", "CAPACITY_FADE",
            "UNDER_DISPATCH", "AUGMENTATION", "HYBRID_ARTEFACT", "HEALTHY"]
    sig_i = {s: i for i, s in enumerate(sigs)}
    scored_rows = m["in_service"] & (m["respondent_freq"] == "M")
    keep = scored_rows.groupby(m["plant_id"]).transform("any")
    m = m[keep].copy()
    m["t_idx"] = m["year"] * 12 + m["month"] - 1
    summ = summ[summ["plant_id"].isin(m["plant_id"].unique())].merge(pl, on="plant_id", how="left")
    summ["owner"] = summ["customer_group"].fillna(summ["owner"]).fillna(summ["operator"]).fillna("Unknown")
    custs = list(summ.groupby("owner")["nameplate_mw"].sum().sort_values(ascending=False).index)
    c_i = {c: i for i, c in enumerate(custs)}
    states, s_i = _idx(summ["state"].fillna("NA"))
    band_med = summ[~summ["hybrid"] & summ["eta_true"].notna()].groupby("dur_band")["eta_true"].median()
    tech_flag = {"FULL_OUTAGE", "PARTIAL_AVAILABILITY", "THERMAL_AUX", "CELL_DEGRADATION", "CAPACITY_FADE", "UNATTRIBUTED"}
    grp = dict(tuple(m.groupby("plant_id")))
    sites = []
    for _, r in summ.iterrows():
        d = grp[r["plant_id"]].sort_values("t_idx")
        scored = (d["in_service"] & (d["respondent_freq"] == "M")).to_numpy()
        flag = d["signature"].isin(tech_flag).to_numpy()
        y = {}
        for yr, dy in d.groupby("year"):
            arr = {k: [None] * 12 for k in ["i", "v", "g", "d", "c", "e", "u"]}
            for _, q in dy.iterrows():
                k = int(q["month"]) - 1
                sc = bool(q["in_service"]) and q["respondent_freq"] == "M"
                arr["i"][k] = r3(q["RTE"]) if sc else None
                arr["v"][k] = rint(q["MWh_at_stake"]) if sc else 0
                arr["g"][k] = sig_i.get(q["signature"], -1) if sc else -1
                arr["d"][k] = rint(q["Discharge"]) if sc else 0
                arr["c"][k] = rint(q["Charge"]) if sc else 0
                arr["u"][k] = r3(q["UTI"]) if sc and pd.notna(q["UTI"]) else None
                arr["e"][k] = r3(roll.get((int(r["plant_id"]), int(q["t_idx"])), np.nan)) if sc else None
            y[str(yr)] = {"mw": round(float(dy["Nameplate_MW"].max()), 1) if dy["Nameplate_MW"].notna().any() else 0,
                          "mwh": round(float(dy["E_rated"].max()), 1) if dy["E_rated"].notna().any() else 0, **arr}
        eta = r["eta_true"] if pd.notna(r["eta_true"]) else None
        dom = r["dominant_signature"] if isinstance(r["dominant_signature"], str) else "HEALTHY"
        span = scored.sum()
        sites.append({
            "n": r["plant_name"], "id": int(r["plant_id"]), "t": tech.index(r["dur_band"]) if r["dur_band"] in tech else 1,
            "c": c_i[r["owner"]], "s": s_i[r["state"] if isinstance(r["state"], str) else "NA"],
            "ssi": int(r["ssi_prospect"] == "SSI customer"),
            "mw": round(float(r["nameplate_mw"] or 0), 1), "mwh": round(float(r["e_rated_mwh"] or 0), 1),
            "la": r3(r["lat"]), "lo": r3(r["lon"]), "oy": rint(r["cod_year"]) if pd.notna(r["cod_year"]) else None,
            "ba": r["ba"] if isinstance(r["ba"], str) else "", "hy": 1 if r["hybrid"] else 0,
            "h24": 1 if span >= 24 else 0, "eta": r3(eta),
            "ix": r3(eta / band_med.get(r["dur_band"], np.nan)) if eta and not r["hybrid"] else None,
            "pa": r3(r["P_aux_pct_nameplate"]) if pd.notna(r["P_aux_pct_nameplate"]) else None,
            "fd": r3(r["fade_pct_per_yr"]) if pd.notna(r["fade_pct_per_yr"]) else None,
            "fs": r["fade_status"] if isinstance(r["fade_status"], str) else "insufficient_history",
            "ce": rint(r["cum_efc"]) if pd.notna(r["cum_efc"]) else 0,
            "wu": r3(r["throughput_used"] * 100) if pd.notna(r["throughput_used"]) else None,
            "dm": sig_i.get(dom, sig_i["HEALTHY"]), "cv": CONV.index(conviction(d["t_idx"].to_numpy(), flag, scored)),
            "tier": r["conviction_tier"] if isinstance(r["conviction_tier"], str) else "-",
            "x": {"ch": r["chem"] if isinstance(r["chem"], str) else "", "en": r["enclosure"] if isinstance(r["enclosure"], str) else "",
                  "ap": r["applications"] if isinstance(r["applications"], str) else "",
                  "hr": r["hybrid_reasons"] if isinstance(r["hybrid_reasons"], str) else ""},
            "y": y})
    pyr = pd.read_parquet(B / "data" / "cache" / "eia860_storage_plant_year.parquet")
    pyr["band"] = pd.cut(pyr["duration_h"], [0, 1.5, 2.5, 4.5, 1e9], labels=tech, right=False).astype(str)
    fleet = {str(i): [round(float(pyr[(pyr["band"] == b) & (pyr["year"] == y)]["nameplate_mw"].sum()), 1) for y in YEARS]
             for i, b in enumerate(tech)}
    data = {"kind": "bess", "fleetCap": fleet, "tech": tech, "states": states, "custs": custs, "sigs": sigs, "conv": CONV, "years": YEARS,
            "band_median_eta": {k: r3(v) for k, v in band_med.items()}, "sites": sites}
    sc = m[m["in_service"] & (m["respondent_freq"] == "M")]
    expect = {"mwh_at_stake_total": float(sc["MWh_at_stake"].sum()),
              "discharge_2025_scored": float(sc.loc[sc["year"] == 2025, "Discharge"].sum()),
              "discharge_2025_all": float(m.loc[m["year"] == 2025, "Discharge"].sum()),
              "eta_median_spec": 0.889, "rte_2025_spec": 0.851, "cap_2025_gw_spec": [40, 43], "discharge_2025_spec_mwh": 26.5e6}
    return data, expect


def clean(o):
    if isinstance(o, dict):
        return {k: clean(v) for k, v in o.items()}
    if isinstance(o, list):
        return [clean(v) for v in o]
    if isinstance(o, float) and not np.isfinite(o):
        return None
    return o


if __name__ == "__main__":
    kind = sys.argv[1]
    data, expect = gas() if kind == "gas" else bess()
    out = Path(__file__).parent / "build"
    out.mkdir(exist_ok=True)
    (out / f"{kind}_data.json").write_text(json.dumps(clean(data), separators=(",", ":"), allow_nan=False))
    (out / f"{kind}_expect.json").write_text(json.dumps(expect, indent=1))
    print(kind, len(data["sites"]), "sites", round((out / f"{kind}_data.json").stat().st_size / 1e6, 2), "MB")
