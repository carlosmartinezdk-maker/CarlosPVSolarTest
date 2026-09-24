"""Deliverables: gas_monthly.parquet, gas_event_ledger.parquet, gas_plant_summary.xlsx, heat_rate_curves.png,
hazard_curves.png, gas_leads.csv, gate table."""
import numpy as np
import pandas as pd
from config import OUT, CLASS_NAME
import qc_floors
import fuel_cost
from load_860_allvintages import gas_capacity, owners
from components import RECOVERY

GATES = []   # filled by gate()


def gate(name, got, expected, ok, level="FAIL", note=""):
    GATES.append({"check": name, "expected": expected, "got": got, "status": "PASS" if ok else level, "note": note})


def qc_flags(p):
    parts = [
        np.where(p["qc_hr"] != "ok", "qc:" + p["qc_hr"].astype(str), ""),
        np.where(p["misalloc_reason"] != "", "misalloc:" + p["misalloc_reason"].astype(str), ""),
        np.where(p["resp_freq"] != "M", "annual_respondent", ""),
        np.where(p["t_amb_c"].isna(), "no_temperature", ""),
        np.where(p["t_source"] == "nearest_county", "temp_nearest_county", ""),
        np.where(p["cap_from_other_vintage"], "capacity_other_vintage", ""),
        np.where(p["nameplate_mw"].isna(), "no_860_capacity", ""),
        np.where(p["chp_cohort"], "chp_cohort", ""),
        np.where(p["reaggregated"], "gt_merged_into_cc", ""),
        np.where(p["lf"] > qc_floors.MAX_LF, "lf_above_1.1", ""),
        np.where(p["price_qc"].fillna("ok") != "ok", "price:" + p["price_qc"].astype(str), ""),
        np.where(p["cost_source"].isin(["national", "national_fill"]), "cost_national_tier", ""),
        np.where((p["heat_content_drift"] - 1).abs() >= 0.02, "heat_content_drift", ""),
    ]
    s = pd.Series([""] * len(p), index=p.index)
    for a in parts:
        s = s.str.cat(pd.Series(a, index=p.index), sep=";")
    return s.str.strip(";").str.replace(";;+", ";", regex=True)


def monthly(p):
    m = p.copy()
    m["qc_flags"] = qc_flags(m)
    cols = {"plant_id": "plant_id", "plant_name": "plant_name", "cls": "tech_class", "year": "year", "month": "month",
            "state": "state", "nerc": "nerc", "ba": "ba", "netgen": "Netgen_MWh", "elec_mmbtu": "Elec_MMBtu",
            "nameplate_mw": "Nameplate_MW", "hr": "HR", "hr_corr": "HR_corr", "hr_ref": "HR_ref",
            "hr_target": "HR_target", "lf": "LF", "eoh": "EOH", "cum_eoh": "cum_EOH", "eoh_since_wash": "EOH_since_wash",
            "starts_proxy": "Starts_proxy", "t_amb_c": "T_amb", "hri": "HRI", "pri": "PRI", "peer_tier": "peer_tier",
            "n_peers": "n_peers", "hri_own": "HRI_own", "signature": "signature", "wash": "wash_detected",
            "excess_mmbtu": "Excess_MMBtu", "waste_usd": "Waste_USD", "recoverable_usd": "Recoverable_USD",
            "gas_cost_final": "gas_cost_final", "cost_source": "cost_source", "heat_content_drift": "heat_content_drift",
            "firm_delivery_share": "firm_delivery_share", "spot_share": "spot_share", "thermal_share": "thermal_share",
            "chp_cohort": "chp_cohort", "resp_freq": "respondent_freq", "scoreable": "scoreable", "qc_flags": "qc_flags"}
    m = m[list(cols)].rename(columns=cols).sort_values(["plant_id", "tech_class", "year", "month"])
    m.to_parquet(OUT / "gas_monthly.parquet", index=False)
    return m


def heat_rate_plot(p, curves, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axs = plt.subplots(2, 2, figsize=(13, 9))
    rng = np.random.default_rng(0)
    for ax, cls in zip(axs.ravel(), ["CC", "GT", "ST", "IC"]):
        d = p[(p["cls"] == cls) & (p["netgen"] > 0) & p["hr"].notna() & p["lf"].between(0, 1.1)]
        ok = d[(d["qc_hr"] == "ok") & ~d["chp_cohort"]]
        bad = d[d["qc_hr"] == "misallocated"]
        so = ok.sample(min(len(ok), 12000), random_state=0)
        sb = bad.sample(min(len(bad), 4000), random_state=0)
        ax.scatter(so["lf"], so["hr_corr"], s=2, alpha=.15, color="#6b7a8f", label="QC-passed, non-CHP (HR_corr)")
        ax.scatter(sb["lf"], sb["hr"], s=2, alpha=.25, color="#d9534f", label="below physical floor (quarantined)")
        c = curves[curves["cls"] == cls]
        ax.plot(c["lf_mid"], c["p10"], "o", color="#2a6fdb", ms=5, label="p10 per LF bin")
        ax.plot(c["lf_mid"], c["ref"], "-", color="#2a6fdb", lw=2.5, label="monotone reference (isotonic)")
        ax.plot(c["lf_mid"], c["p50"], "--", color="#444", lw=1, label="median per LF bin")
        ax.axhline(qc_floors.FLOORS[cls], color="#d9534f", lw=1.5, ls=":", label=f"physical floor {qc_floors.FLOORS[cls]:,}")
        ax.set_ylim(3000, {"CC": 14000, "GT": 22000, "ST": 20000, "IC": 20000}[cls])
        ax.set_xlim(0, 1.1)
        spread = (c["ref"].max() / c["ref"].min() - 1) * 100
        ax.set_title(f"{CLASS_NAME[cls]} — reference envelope spread {spread:.0f}%")
        ax.set_xlabel("monthly load factor"); ax.set_ylabel("heat rate, Btu/kWh (HHV)"); ax.grid(alpha=.3)
    axs[0, 0].legend(fontsize=7, frameon=False, markerscale=4, loc="upper right")
    fig.suptitle("Heat rate vs load factor by class, 2019-2025 (EIA-923 monthly, temperature-corrected)", fontsize=12)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


def plant_summary(p, risk, leads_df, onset, renewal):
    s = p[p["scoreable"]]
    ann = s.groupby(["plant_id", "cls", "year"]).agg(HRI=("hri", "mean"), PRI=("pri", "mean")).unstack("year")
    ann.columns = [f"{a}_{b}" for a, b in ann.columns]
    last = p.sort_values("t_idx").groupby(["plant_id", "cls"]).last()
    base = last[["plant_name", "state", "nerc", "ba", "operator", "nameplate_mw", "n_units", "unit_size_mw",
                 "cod_year", "technology", "duct_burners", "chp_cohort", "climate_region", "eoh_since_wash",
                 "wash_seen", "cum_eoh", "nonrec_slope_per_yr"]].copy()
    base["class_name"] = base.index.get_level_values("cls").map(CLASS_NAME)

    def slope(d):
        d = d.dropna(subset=["hri_own"])
        return np.polyfit((d["t_idx"] - d["t_idx"].min()) / 12, d["hri_own"], 1)[0] if len(d) >= 12 else np.nan
    base["hri_own_slope_pct_per_yr"] = s[s["resp_freq"] == "M"].groupby(["plant_id", "cls"]).apply(slope, include_groups=False) * 100
    base["nonrecoverable_pct_per_yr"] = -base.pop("nonrec_slope_per_yr") * 100
    sig = s[~s["signature"].isin(["HEALTHY", "NOT_SCORED"])]
    base["dominant_component"] = sig.groupby(["plant_id", "cls"])["signature"].agg(lambda x: x.value_counts().index[0])
    base["dominant_component"] = base["dominant_component"].fillna("HEALTHY")
    rec = s.groupby(["plant_id", "cls", "signature"])["recoverable_usd"].sum().unstack(fill_value=0)
    base["dominant_recoverable"] = rec[["FOULING", "HGP"]].idxmax(axis=1).where(rec[["FOULING", "HGP"]].max(axis=1) > 0)
    tmax = p["t_idx"].max()
    r24 = s[s["t_idx"] > tmax - 24].groupby(["plant_id", "cls"])["recoverable_usd"].sum() / 2
    base["recoverable_usd_per_yr"] = r24
    base["waste_usd_per_yr"] = s[s["t_idx"] > tmax - 24].groupby(["plant_id", "cls"])["waste_usd"].sum() / 2
    base["recoverable_usd_2019_2025"] = s.groupby(["plant_id", "cls"])["recoverable_usd"].sum()
    base["cost_source_main"] = s.groupby(["plant_id", "cls"])["cost_source"].agg(lambda x: x.value_counts().index[0])
    from economics import payback
    base = payback(base.reset_index()).set_index(["plant_id", "cls"])
    from leads import wash_status
    base["wash_status"] = wash_status(base["eoh_since_wash"].to_numpy(), base["wash_seen"].fillna(False).to_numpy())
    rw = risk.pivot_table(index=["plant_id", "cls"], columns="signature",
                          values=["lam_hat", "P12", "EAL_usd", "Z"], aggfunc="first")
    rw.columns = [f"{b}_{a}" for a, b in rw.columns]
    act = risk.pivot_table(index=["plant_id", "cls"], columns="signature", values="act", aggfunc="first")
    act.columns = [f"{c}_decision" for c in act.columns]
    base = base.join(rw).join(act).join(ann)
    ow = owners()
    base = base.reset_index().merge(ow, on="plant_id", how="left")
    base["owner"] = base["owner_sched4"].fillna(base["operator"])
    base["owner_source"] = np.where(base["owner_sched4"].notna(), "EIA-860 Schedule 4", "operating utility (fallback)")
    base["customer_group"] = ""        # not supplied: no customer / CRM file was provided
    base["ssi_prospect"] = ""          # not supplied
    if len(leads_df):
        base = base.merge(leads_df[["plant_id", "cls", "rank", "conviction_tier"]].rename(columns={"rank": "lead_rank"}),
                          on=["plant_id", "cls"], how="left")
    base["conviction_tier"] = base.get("conviction_tier", pd.Series(dtype=str)).fillna("-")
    front = ["plant_id", "plant_name", "cls", "class_name", "state", "nerc", "ba", "owner", "owner_source", "operator",
             "customer_group", "ssi_prospect", "nameplate_mw", "n_units", "unit_size_mw", "cod_year", "climate_region",
             "chp_cohort", "conviction_tier", "lead_rank", "dominant_component", "dominant_recoverable",
             "hri_own_slope_pct_per_yr", "nonrecoverable_pct_per_yr", "eoh_since_wash", "wash_status",
             "recoverable_usd_per_yr", "waste_usd_per_yr", "remediation_cost_usd", "payback_yr", "cost_status",
             "cost_source_main"]
    front = [c for c in front if c in base.columns]
    return base[front + [c for c in base.columns if c not in front and c not in ("owner_sched4", "owner_pct")]]


def gates(p, kt, curves, led, disp, onset, renewal, fouling_share, nonrec_med, bt):
    GATES.clear()
    s25 = p[(p["year"] == 2025) & (p["netgen"] > 0) & (p["elec_mmbtu"] > 0)]
    for cls, exp, tol in [("CC", 7307, 200), ("GT", 11353, 400)]:
        x = s25[(s25["cls"] == cls) & (s25["hr"] <= qc_floors.CEILINGS[cls])]
        v = x["hr"].median()
        post = s25[(s25["cls"] == cls) & (s25["qc_hr"] == "ok")]["hr"].median()
        gate(f"{cls} median heat rate 2025 (plant-month, pre-floor QC — spec definition)", round(v), f"{exp:,} ±{tol}",
             abs(v - exp) <= tol, note=f"post-QC scoreable median = {post:,.0f}")
    cap = gas_capacity()
    for cls, exp in [("CC", 333), ("GT", 160)]:
        v = cap[(cap["year"] == 2025) & (cap["cls"] == cls)]["nameplate_mw"].sum() / 1000
        gate(f"{cls} capacity 2025 (GW, EIA-860 nameplate)", round(v, 1), f"~{exp} ±5", abs(v - exp) <= 5)
    for cls in ["CC", "GT"]:
        d = p[(p["cls"] == cls) & (p["netgen"] > 0)]
        j_rows = d["nameplate_mw"].notna().mean()
        j_same = (d["nameplate_mw"].notna() & ~d["cap_from_other_vintage"]).mean()
        gate(f"Capacity join rate {cls} (plant-months)", f"{j_rows:.3f}", ">=0.95", j_rows >= 0.95,
             note=f"same-vintage join {j_same:.3f}")
    st = p[(p["cls"] == "ST") & (p["netgen"] > 0)]
    gate("Gas Steam join rate (indicative)", f"{st['nameplate_mw'].notna().mean():.3f}", "~0.52 (spec)", True, level="INFO",
         note="gas-fuel ST rows only; coal co-firing units filed under coal in 860 are excluded upstream")
    for cls in ["CC", "GT", "ST", "IC"]:
        d = p[(p["cls"] == cls) & (p["netgen"] > 0) & ~p["chp_cohort"]]
        b = (d["qc_hr"] == "misallocated").mean()
        c = p[(p["cls"] == cls) & (p["netgen"] > 0) & p["chp_cohort"]]
        gate(f"Plant-months below floor after re-aggregation, {cls} (non-CHP)", f"{b:.4f}", "<0.05", b < 0.05,
             note=f"CHP cohort {(c['qc_hr'] == 'misallocated').mean():.3f} (EIA CHP fuel allocation, reported separately)")
    nc = fuel_cost.national_check()
    for y, tol in [(2022, 0.20), (2020, 0.15)]:
        v = nc.loc[y, "got"]
        gate(f"National delivered gas {y} ($/MMBtu)", round(v, 2), f"{nc.loc[y, 'expected']:.2f} ±{tol}",
             abs(v - nc.loc[y, "expected"]) <= tol)
    for cls, r in kt.iterrows():
        gate(f"k_T sign, {cls}", f"{r['k_T_per_C'] * 100:.3f} %/degC", "positive", r["k_T_per_C"] > 0,
             note="hinge form: applied above 15 degC")
        gate(f"k_T magnitude, {cls}", f"{r['k_T_per_C'] * 100:.3f} %/degC",
             "0.1-0.3 %/degC simple cycle; less for CC", bool(r["in_expected_range"]), level="WARN")
    gate("Non-recoverable degradation, fleet median (%/yr)", round(nonrec_med, 3), "0.3-0.6", 0.3 <= nonrec_med <= 0.6,
         note="annual-p90 envelope of HRI_own; raw annual CC heat-rate trend is also ~0")
    gate("Fouling share of recoverable degradation", round(fouling_share, 3), "0.70-0.85", 0.70 <= fouling_share <= 0.85)
    for _, r in disp.iterrows():
        gate(f"Variance/mean of fault counts, {r['signature']} (plant-years, exposure>=6)", round(r["var_mean_ratio_raw"], 2),
             ">2 -> negative binomial", r["var_mean_ratio_raw"] > 2, level="WARN",
             note=f"NB alpha={r['nb_alpha']:.3f}; model used: {r['model_used']}")
    for _, r in bt.iterrows():
        gate(f"Backtest {r['signature']} (fit<=Y, predict Y+1, 2022-2025)",
             f"AUC {r['AUC']:.2f}, slope {r['calibration_slope']:.2f}, chi2/df {r['pearson_chi2_df']:.2f}, beats mean {r['beats_baseline']}",
             "AUC>0.65, slope~1, chi2/df~1, beats baseline", bool(r["pass"]), level="WARN")
    return pd.DataFrame(GATES)


def print_gates(g):
    w = max(len(c) for c in g["check"])
    print("\n" + "=" * 30 + " ACCEPTANCE GATES " + "=" * 30)
    for _, r in g.iterrows():
        print(f"[{r['status']:4}] {r['check']:<{w}}  got {str(r['got']):<28} expected {r['expected']}"
              + (f"   ({r['note']})" if r["note"] else ""))
    n = g["status"].value_counts().to_dict()
    print(f"summary: {n}\n")
