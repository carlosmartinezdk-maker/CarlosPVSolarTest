"""BESS deliverables and gate table."""
import numpy as np
import pandas as pd
from config import OUT
from load_860_allvintages import owners, APPS
import sys as _sys
from config import ROOT as _ROOT
_sys.path.insert(0, str(_ROOT.parent))
from crm import customers  # noqa: E402

GATES = []


def gate(name, got, expected, ok, level="FAIL", note=""):
    GATES.append({"check": name, "expected": expected, "got": got, "status": "PASS" if ok else level, "note": note})


def qc_flags(p):
    parts = [np.where(p["hybrid"], "hybrid:" + p["hybrid_reasons"].astype(str), ""),
             np.where(p["soc_drift"], "soc_drift_rte_unreliable", ""),
             np.where(p["resp_freq"] != "M", "annual_respondent", ""),
             np.where(~p["in_service"], "not_in_service", ""),
             np.where(p["cap_from_other_vintage"], "e_rated_other_vintage", ""),
             np.where(p["e_rated_mwh"].isna(), "no_860_energy_capacity", ""),
             np.where(p["t_amb_c"].isna(), "no_temperature", ""),
             np.where(p["envelope_breach"], "ambient_outside_assumed_envelope", ""),
             np.where(p["uti"].isna() & p["in_service"], "no_peer_uti", ""),
             np.where(p["duration_h"] < 0.25, "implausible_e_rated", "")]
    s = pd.Series([""] * len(p), index=p.index)
    for a in parts:
        s = s.str.cat(pd.Series(a, index=p.index), sep=";")
    return s.str.strip(";").str.replace(";;+", ";", regex=True)


def monthly(p):
    m = p.copy()
    m["quality_flags"] = qc_flags(m)
    cols = {"plant_id": "plant_id", "plant_name": "plant_name", "year": "year", "month": "month", "state": "state",
            "ba": "ba", "charge": "Charge", "discharge": "Discharge", "rte": "RTE", "efc": "EFC", "uti": "UTI",
            "peer_efc_median": "peer_EFC_median", "peer_tier": "peer_tier", "e_rated_mwh": "E_rated",
            "nameplate_mw": "Nameplate_MW", "duration_h": "Duration", "dur_band": "duration_band", "t_amb_c": "T_amb",
            "cum_efc": "cum_EFC", "throughput_used": "throughput_used", "signature": "signature",
            "mwh_at_stake": "MWh_at_stake", "recoverable_mwh": "recoverable_MWh", "rte_pts_lost": "RTE_pts_lost",
            "hybrid": "hybrid", "in_service": "in_service", "resp_freq": "respondent_freq",
            "quality_flags": "quality_flags"}
    m = m[list(cols)].rename(columns=cols).sort_values(["plant_id", "year", "month"])
    m.to_parquet(OUT / "bess_monthly.parquet", index=False)
    return m


def decomposition_csv(dec, p):
    site = p.sort_values("t_idx").groupby("plant_id").last()[["plant_name", "nameplate_mw", "e_rated_mwh", "dur_band",
                                                              "enclosure", "hybrid"]]
    d = dec.drop(columns=["hybrid"], errors="ignore").merge(site.reset_index(), on="plant_id", how="left")
    d["P_aux_pct_nameplate"] = d["P_aux_mw"] / d["nameplate_mw"] * 100
    d["hvac_excess_pct_nameplate"] = d["hvac_excess_mw"] / d["nameplate_mw"] * 100
    cols = ["plant_id", "plant_name", "hybrid", "dur_band", "enclosure", "nameplate_mw", "usable_months", "n", "fit_ok",
            "eta_true", "P_aux_mw", "P_aux_pct_nameplate", "P_aux_summer_mw", "P_aux_shoulder_mw", "P_aux_winter_mw",
            "hvac_excess_mw", "hvac_excess_pct_nameplate", "naive_rte", "naive_rte_mean_month", "naive_rte_median_month", "r2", "se_a", "se_b",
            "eta_trend_pts_per_yr", "paux_trend_pct_per_yr", "trend_status"]
    d = d[[c for c in cols if c in d.columns]]
    d.to_csv(OUT / "bess_efficiency_decomposition.csv", index=False)
    return d


def decomposition_plot(d, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    ok = d[d["fit_ok"] == True]
    col = {"<1.5h": "#d9822b", "1.5-2.5h": "#2a6fdb", "2.5-4.5h": "#3d9970", ">4.5h": "#8e44ad"}
    fig, ax = plt.subplots(figsize=(10, 6.5))
    for band, c in col.items():
        for hyb, mk in [(False, "o"), (True, "x")]:
            x = ok[(ok["dur_band"] == band) & (ok["hybrid"] == hyb)]
            ax.scatter(x["P_aux_pct_nameplate"], x["eta_true"], s=18, c=c, marker=mk, alpha=.6 if not hyb else .35,
                       label=f"{band} {'hybrid' if hyb else 'standalone'} (n={len(x)})")
    em, pm, nm = ok["eta_true"].median(), ok["P_aux_pct_nameplate"].median(), ok["naive_rte_mean_month"].median()
    ax.axhline(em, color="k", lw=1.2, ls="--"); ax.axvline(pm, color="k", lw=1.2, ls="--")
    ax.axhline(nm, color="#d9534f", lw=1.2, ls=":")
    ax.text(ax.get_xlim()[0] if False else -0.9, em + 0.004, f"median eta_true = {em:.3f}", fontsize=9)
    ax.text(1.6, nm + 0.004, f"median naive RTE (same sites) = {nm:.3f}", fontsize=9, color="#d9534f")
    ax.text(pm + 0.05, 0.53, f"median P_aux = {pm:.2f}% of nameplate", fontsize=9)
    ax.set_xlim(-1, 3); ax.set_ylim(0.5, 1.0)
    ax.set_xlabel("parasitic load P_aux, % of nameplate MW  (slope of C/D on h/D)")
    ax.set_ylabel("true conversion efficiency eta_true  (1 / intercept)")
    ax.set_title("Auxiliary-load decomposition of apparent round-trip efficiency, US BESS 2019-2025\n"
                 "Charge/Discharge = 1/eta + P_aux * hours/Discharge, fitted per site on monthly EIA-923")
    ax.grid(alpha=.3); ax.legend(fontsize=7, frameon=False, ncol=2, loc="lower right")
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)


def site_summary(p, dec, fd, risk, L):
    s = p[p["in_service"]]
    ann = s.groupby(["plant_id", "year"]).agg(D=("discharge", "sum"), C=("charge", "sum"), EFC=("efc", "sum"),
                                              UTI=("uti", "median"))
    ann["RTE"] = ann["D"] / ann["C"].where(ann["C"] > 0)
    w = ann[["RTE", "EFC", "UTI"]].unstack("year")
    w.columns = [f"{a}_{b}" for a, b in w.columns]
    last = p.sort_values("t_idx").groupby("plant_id").last()
    b = last[["plant_name", "state", "ba", "operator", "nameplate_mw", "e_rated_mwh", "duration_h", "dur_band",
              "cod_year", "chem", "enclosure", "hybrid", "hybrid_reasons", "cum_efc", "throughput_used",
              "max_charge_mw", "max_discharge_mw"]].copy()
    b["applications"] = last[[c for c in APPS if c in last]].apply(lambda r: ", ".join(c for c in r.index if r[c] == "Y"), axis=1)
    b["asym_rated"] = b["max_discharge_mw"] / b["max_charge_mw"].where(b["max_charge_mw"] > 0)
    pk = s.groupby("plant_id").agg(pd_=("discharge", "max"), pc=("charge", "max"))
    b["asym_realised_avgpower_proxy"] = pk["pd_"] / pk["pc"].where(pk["pc"] > 0)
    b["warranty_cycles_assumed"] = 6000
    b["warranty_headroom"] = (1 - b["throughput_used"]).clip(lower=0)
    b["envelope_breach_months"] = s.groupby("plant_id")["envelope_breach"].sum()
    b["availability_months"] = s[s["signature"].isin(["FULL_OUTAGE", "PARTIAL_AVAILABILITY"])].groupby("plant_id").size()
    b["availability_months"] = b["availability_months"].fillna(0).astype(int)
    sc = s[~s["signature"].isin(["HEALTHY", "NO_DATA", "NOT_IN_SERVICE", "ANNUAL_RESPONDENT"])]
    b["dominant_signature"] = sc.groupby("plant_id")["signature"].agg(lambda x: x.value_counts().index[0])
    b["dominant_signature"] = b["dominant_signature"].fillna("HEALTHY")
    b["mwh_at_stake_total"] = s.groupby("plant_id")["mwh_at_stake"].sum()
    b = b.join(dec.set_index("plant_id")[["eta_true", "P_aux_mw", "hvac_excess_mw", "eta_trend_pts_per_yr",
                                          "paux_trend_pct_per_yr", "trend_status", "naive_rte", "naive_rte_mean_month", "n", "r2"]])
    b["P_aux_pct_nameplate"] = b["P_aux_mw"] / b["nameplate_mw"] * 100
    b = b.join(fd.set_index("plant_id")[["fade_pct_per_yr", "fade_status"]])
    rw = risk.pivot_table(index="plant_id", columns="signature", values=["P12", "EAL_MWh", "lam_hat"], aggfunc="first")
    rw.columns = [f"{a}_{c}" for a, c in rw.columns]
    b = b.join(rw).join(w).reset_index()
    ow = owners()
    b = b.merge(ow, on="plant_id", how="left")
    b["owner"] = b["owner_sched4"].fillna(b["operator"])
    b = customers.assign(b, "BESS")
    b["ssi_prospect"] = b["ssi_status"]
    if len(L):
        b = b.merge(L[["plant_id", "rank", "conviction_tier", "dominant_reason"]].rename(columns={"rank": "lead_rank"}),
                    on="plant_id", how="left")
    front = ["plant_id", "plant_name", "state", "ba", "owner", "operator", "customer_group", "ssi_prospect", "customer_source", "hybrid",
             "hybrid_reasons", "chem", "enclosure", "applications", "nameplate_mw", "e_rated_mwh", "duration_h",
             "dur_band", "cod_year", "lead_rank", "conviction_tier", "dominant_signature", "eta_true", "naive_rte_mean_month",
             "P_aux_pct_nameplate", "hvac_excess_mw", "eta_trend_pts_per_yr", "paux_trend_pct_per_yr", "trend_status",
             "fade_pct_per_yr", "fade_status", "cum_efc", "throughput_used", "warranty_headroom", "warranty_cycles_assumed",
             "envelope_breach_months", "availability_months", "asym_rated", "asym_realised_avgpower_proxy", "mwh_at_stake_total"]
    front = [c for c in front if c in b.columns]
    return b[front + [c for c in b.columns if c not in front and c not in ("owner_sched4", "owner_pct", "ssi", "ssi_status")]]


def reliability_gates(disp, bt):
    for _, r in disp.iterrows():
        gate(f"Variance/mean of fault counts, {r['signature']}", round(r["var_mean_ratio"], 2), ">1 (overdispersion -> NB)",
             r["var_mean_ratio"] > 1.5, level="WARN", note=f"NB alpha={r['nb_alpha']:.3f}; used: {r['model_used']}")
    for _, r in bt.iterrows():
        gate(f"Backtest {r['signature']} (fit<=Y, predict Y+1, 2023-2025)",
             f"AUC {r['AUC']:.2f}, slope {r['calibration_slope']:.2f}, chi2/df {r['pearson_chi2_df']:.1f}",
             "AUC>0.65, slope~1, chi2/df~1, beats mean", bool(r["pass"]), level="WARN",
             note=f"{r['share_new_sites'] * 100:.0f}% of test plant-years are sites with no prior history; beats mean: {r['beats_baseline']}")
    return pd.DataFrame(GATES)


def gates(p, dec):
    GATES.clear()
    p25 = p[(p["year"] == 2025) & ~p["hybrid"]]
    a = p25.groupby("plant_id")[["charge", "discharge"]].sum()
    a = a[a["charge"] > 0]
    med = (a["discharge"] / a["charge"]).median()
    gate("Fleet median apparent RTE 2025, standalone (site annual D/C)", round(med, 3), "0.851 ±0.02", abs(med - 0.851) <= 0.02,
         note=f"median of monthly RTE {p25['rte'].median():.3f}; throughput-weighted {a['discharge'].sum() / a['charge'].sum():.3f}")
    ok = dec[dec["fit_ok"] == True]
    e, n = ok["eta_true"].median(), ok["naive_rte_mean_month"].median()
    gate("Decomposed eta_true, fleet median", round(e, 3), "0.889 ±0.02", abs(e - 0.889) <= 0.02,
         note=f"p10 {ok['eta_true'].quantile(.1):.3f}, p90 {ok['eta_true'].quantile(.9):.3f}; standalone only "
              f"{ok.loc[~ok['hybrid'], 'eta_true'].median():.3f}")
    gate("Naive RTE on the same fitted sites (site mean of monthly RTE)", round(n, 3), "0.844 ±0.02", abs(n - 0.844) <= 0.02,
         note=f"throughput-weighted per site {ok['naive_rte'].median():.3f}")
    gap = (e - n) * 100
    gate("Gap eta_true - naive (points)", round(gap, 2), "~4.5 ±1.5", abs(gap - 4.5) <= 1.5,
         note=f"with throughput-weighted naive: {(e - ok['naive_rte'].median()) * 100:.2f}")
    gate("eta_true above naive RTE (regression not inverted)", bool(e > n), "True", e > n)
    pct = ok["P_aux_mw"] / ok["nameplate_mw"] * 100
    gate("P_aux % of nameplate, median", round(pct.median(), 3), "0.21 (p90 < ~1%)", 0.1 <= pct.median() <= 0.35 and pct.quantile(.9) < 1.0,
         note=f"p10 {pct.quantile(.1):.2f}%, p90 {pct.quantile(.9):.2f}%")
    gate("Sites with a usable aux decomposition", f"{len(ok)} of {p['plant_id'].nunique()}", "~600 of ~960",
         450 <= len(ok) <= 750)
    for y, exp, tol in [(2025, 26.5e6, 1e6), (2019, 430e3, 30e3)]:
        v = p.loc[p["year"] == y, "discharge"].sum()
        gate(f"Total BESS discharge {y} (MWh)", f"{v:,.0f}", f"{exp:,.0f} ±{tol:,.0f}", abs(v - exp) <= tol)
    from load_860_allvintages import plant_year
    py = plant_year()
    v = py.loc[py["year"] == 2025, "nameplate_mw"].sum() / 1e3
    gate("BESS nameplate 2025 (GW, EIA-860 3_4 BA)", round(v, 1), "~40-43", 40 <= v <= 43, level="WARN",
         note="year-end operable incl. units commissioned late 2025")
    d = py.loc[py["year"] == 2025, "duration_h"].median()
    gate("Median duration 2025 (h)", round(d, 2), "2.0", abs(d - 2.0) <= 0.25)
    j = p["e_rated_mwh"].notna().mean()
    gate("Capacity join rate to EIA-860 (plant-months)", f"{j:.4f}", ">=0.98", j >= 0.98,
         note=f"same-vintage {(p['e_rated_mwh'].notna() & ~p['cap_from_other_vintage']).mean():.4f}")
    fl = a["discharge"].sum() / a["charge"].sum()
    gate("Fleet RTE vs EIA published anchor (standalone 2025, throughput-weighted)", round(fl, 3), "~0.82-0.85 (and <0.95)",
         fl < 0.95, level="FAIL", note="above 0.95 would mean hybrids included or Quantity/Grossgen swapped")
    return pd.DataFrame(GATES)


def print_gates(g):
    w = max(len(c) for c in g["check"])
    print("\n" + "=" * 30 + " BESS ACCEPTANCE GATES " + "=" * 30)
    for _, r in g.iterrows():
        print(f"[{r['status']:4}] {r['check']:<{w}}  got {str(r['got']):<22} expected {r['expected']}"
              + (f"   ({r['note']})" if r["note"] else ""))
    print("summary:", g["status"].value_counts().to_dict(), "\n")
