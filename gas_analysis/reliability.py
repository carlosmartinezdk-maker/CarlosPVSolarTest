"""R4 negative-binomial rate model, R5 credibility shrinkage, R6 probability / EAL, R7 decision rule, R8 backtest."""
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.metrics import roc_auc_score

FAULT_SIGS = ["FOULING", "HGP", "CYCLING", "COOLING_DEGRADATION", "BOP_INTERMITTENT"]
POOL_MIN_UNITS = 5
POOL_MIN_EXPOSURE = 120          # exposure-months
BACKTEST_YEARS = [2021, 2022, 2023, 2024]
EAL_RECENT_MONTHS = 12
LAM_FLOOR = 1e-4                 # events per exposure-month; avoids zero predicted means


def unit_frame(p):
    """Static covariates per plant x class (latest year)."""
    last = p.sort_values("t_idx").groupby(["plant_id", "cls"]).last()
    u = last[["size_band", "cod_year", "nerc", "climate_region", "duct_burners", "chp_cohort", "unit_size_mw",
              "n_units", "nameplate_mw"]].copy()
    u["vintage_band"] = (np.floor(u["cod_year"].fillna(1990) / 10) * 10).astype(int)
    fd = p.groupby(["plant_id", "cls"])["firm_delivery_share"].mean().rename("firm_delivery_mean")
    return u.join(fd).reset_index()


def model_frame(led, p):
    yr = p.groupby(["plant_id", "cls", "year"]).agg(age=("age_yr", "mean"), cum_eoh=("cum_eoh", "max"))
    d = led[led["signature"].isin(FAULT_SIGS) & (led["exposure_months"] > 0)] \
        .merge(yr.reset_index(), on=["plant_id", "cls", "year"], how="left") \
        .merge(unit_frame(p), on=["plant_id", "cls"], how="left")
    d["log_age"] = np.log1p(d["age"].clip(lower=0).fillna(d["age"].median()))
    d["log_ceoh"] = np.log1p(d["cum_eoh"].fillna(0) / 1000)
    d["size_band"] = d["size_band"].fillna(-1).astype(int).astype(str)
    d["firm"] = d["firm_delivery_mean"].fillna(1.0)
    d["duct"] = (d["duct_burners"] == "Y").astype(int)
    d["chp"] = d["chp_cohort"].astype(int)
    d["nerc"] = d["nerc"].fillna("NA").astype(str)
    d["climate_region"] = d["climate_region"].fillna("inland")
    return d


FORMULA = ("K ~ C(cls) + log_age + log_ceoh + C(size_band) + C(vintage_band) + C(climate_region) + C(nerc) "
           "+ firm + duct + chp")


def fit_rate_models(mf):
    rows, fits = [], {}
    for s in FAULT_SIGS:
        d = mf[mf["signature"] == s].copy()
        d = d[d["K"].notna()]
        disp_raw = d.loc[d["exposure_months"] >= 6, "K"].var() / d.loc[d["exposure_months"] >= 6, "K"].mean()
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pois = smf.glm(FORMULA, d, family=sm.families.Poisson(), offset=np.log(d["exposure_months"])).fit()
            pearson = pois.pearson_chi2 / pois.df_resid
            try:
                nb = smf.negativebinomial(FORMULA, d, offset=np.log(d["exposure_months"])).fit(disp=0, maxiter=300)
                alpha = float(nb.params["alpha"])
                llnb = nb.llf
            except Exception:
                nb, alpha, llnb = None, np.nan, np.nan
        rows.append({"signature": s, "n_plant_years": len(d), "events": int(d["K"].sum()),
                     "var_mean_ratio_raw": disp_raw, "poisson_pearson_disp": pearson, "nb_alpha": alpha,
                     "phi": 1 / alpha if alpha and alpha > 1e-6 else np.inf, "ll_poisson": pois.llf, "ll_nb": llnb,
                     "lr_nb_vs_poisson": 2 * (llnb - pois.llf) if nb is not None else np.nan,
                     "model_used": "negative binomial" if (nb is not None and alpha > 1e-3) else "poisson (alpha~0)"})
        fits[s] = nb if nb is not None else pois
        if nb is not None:
            coef = nb.params.drop("alpha")
            fits[s + "_coef"] = pd.DataFrame({"coef": coef, "se": nb.bse.drop("alpha"),
                                              "rate_ratio": np.exp(coef), "p": nb.pvalues.drop("alpha")})
    return pd.DataFrame(rows), fits


def _pool_rate(tab, keys):
    g = tab.groupby(keys).agg(K=("K", "sum"), E=("exposure_months", "sum"), n=("plant_id", "nunique"))
    g = g[(g["n"] >= POOL_MIN_UNITS) & (g["E"] >= POOL_MIN_EXPOSURE)]
    return (g["K"] / g["E"]).rename("lam")


def shrink(led_s, units, phi):
    """Credibility-weighted rate per plant x class for one signature. led_s: plant-year rows (K, exposure)."""
    own = led_s.groupby(["plant_id", "cls"]).agg(K_own=("K", "sum"), E_own=("exposure_months", "sum")).reset_index()
    tab = led_s.merge(units, on=["plant_id", "cls"], how="left")
    own = own.merge(units, on=["plant_id", "cls"], how="left")
    own["lam_pool"] = np.nan
    own["pool_level"] = ""
    ladders = [["cls", "size_band", "vintage_band", "nerc"], ["cls", "climate_region"], ["cls"]]
    for lvl, keys in enumerate(ladders, 1):
        r = _pool_rate(tab, keys)
        m = own["lam_pool"].isna()
        v = own.loc[m, keys].merge(r.reset_index(), on=keys, how="left")["lam"].to_numpy()
        own.loc[m, "lam_pool"] = v
        own.loc[m & own["lam_pool"].notna(), "pool_level"] = "+".join(keys)
    fleet = tab["K"].sum() / max(tab["exposure_months"].sum(), 1)
    m = own["lam_pool"].isna()
    own.loc[m, "lam_pool"], own.loc[m, "pool_level"] = fleet, "fleet"
    lam_pool = own["lam_pool"].clip(lower=LAM_FLOOR)
    tau = (phi / lam_pool) if np.isfinite(phi) else np.full(len(own), np.inf)   # Buhlmann: process var / VHM
    own["tau"] = tau
    own["Z"] = np.where(np.isfinite(tau), own["E_own"] / (own["E_own"] + tau), 0.0)
    own["lam_hat"] = (own["Z"] * own["K_own"] / own["E_own"].clip(lower=1) + (1 - own["Z"]) * own["lam_pool"]).clip(lower=LAM_FLOOR)
    return own


def p12(lam, phi):
    lam = np.asarray(lam, float)
    if not np.isfinite(phi):
        return 1 - np.exp(-lam * 12)
    return 1 - (1 + lam * 12 / phi) ** (-phi)


def risk_table(p, led, ep, lbar, disp, onset, renewal, units):
    recent = p[p["t_idx"] > p["t_idx"].max() - EAL_RECENT_MONTHS]
    base = recent.groupby(["plant_id", "cls"]).agg(mmbtu_month=("elec_mmbtu", "mean"),
                                                   gas_cost=("gas_cost_final", "mean")).reset_index()
    delta = ep.groupby("signature")["mean_deficit_pct"].mean() / 100
    best = {}
    for s in FAULT_SIGS:
        o = onset[(onset["signature"] == s) & onset["k"].notna()] if "k" in onset else pd.DataFrame()
        cand = [o]
        if s == "FOULING" and len(renewal):
            cand.append(renewal)
        c = pd.concat(cand).dropna(subset=["aic"]) if len(pd.concat(cand)) else pd.DataFrame()
        best[s] = c.sort_values("aic").iloc[0] if len(c) else None
    out = []
    for s in FAULT_SIGS:
        phi = float(disp.loc[disp["signature"] == s, "phi"].iat[0])
        o = shrink(led[led["signature"] == s], units, phi).merge(base, on=["plant_id", "cls"], how="left")
        o["signature"] = s
        o["phi"] = phi
        o["P12"] = p12(o["lam_hat"], phi)
        o["L_bar_months"] = lbar.get(s, np.nan)
        o["delta_bar"] = delta.get(s, np.nan)
        o["EAL_usd"] = o["lam_hat"] * 12 * o["L_bar_months"] * o["delta_bar"] * o["mmbtu_month"] * o["gas_cost"]
        b = best[s]
        o["hazard_axis"] = None if b is None else b["axis"]
        o["hazard_k"] = np.nan if b is None else b["k"]
        o["hazard_shape"] = None if b is None else b["shape"]
        out.append(o)
    return pd.concat(out, ignore_index=True)


def decision(risk, recovery, cost_table, horizon):
    ct = cost_table.set_index("signature")
    r = risk.copy()
    r["recovery"] = r["signature"].map(recovery)
    fixed = r["signature"].map(ct["fixed_usd_per_unit"]).fillna(0)
    per = r["signature"].map(ct["usd_per_mw_of_unit"]).fillna(0)
    r["preventative_cost_usd"] = r["n_units"].fillna(1) * (fixed + per * r["unit_size_mw"].fillna(0))
    r["benefit_usd"] = r["EAL_usd"] * r["recovery"] * horizon
    wear = r["hazard_shape"].fillna("").str.startswith("wear-out")
    econ = r["benefit_usd"] > r["preventative_cost_usd"]
    norec = r["recovery"].fillna(0) <= 0
    r["act"] = np.select([norec, wear & econ, wear & ~econ, ~wear & (r["hazard_shape"].fillna("").str.startswith("infant"))],
                         ["no: not recoverable by maintenance (operating regime)", "ACT: preventative work pays back", "no: cost exceeds benefit",
                          "no: infant-mortality shape -> commissioning QA / warranty"], default="no: random hazard, run to condition")
    return r


def backtest(led, units, disp):
    rows = []
    for s in FAULT_SIGS:
        phi = float(disp.loc[disp["signature"] == s, "phi"].iat[0])
        ls = led[led["signature"] == s]
        preds = []
        for y in BACKTEST_YEARS:
            train = ls[ls["year"] <= y]
            test = ls[(ls["year"] == y + 1) & (ls["exposure_months"] > 0)]
            sh = shrink(train, units, phi)
            fleet = train["K"].sum() / max(train["exposure_months"].sum(), 1)
            t = test.merge(sh[["plant_id", "cls", "lam_hat"]], on=["plant_id", "cls"], how="left")
            t["lam_hat"] = t["lam_hat"].fillna(fleet).clip(lower=LAM_FLOOR)
            t["mu"] = t["lam_hat"] * t["exposure_months"]
            t["mu0"] = max(fleet, LAM_FLOOR) * t["exposure_months"]
            nb_p = (lambda mu: 1 - (1 + mu / phi) ** (-phi)) if np.isfinite(phi) else (lambda mu: 1 - np.exp(-mu))
            t["p"] = nb_p(t["mu"])
            t["p0"] = nb_p(t["mu0"])
            t["y"] = (t["K"] > 0).astype(int)
            t["test_year"] = y + 1
            preds.append(t)
        t = pd.concat(preds)
        var = t["mu"] + (t["mu"] ** 2 / phi if np.isfinite(phi) else 0)
        chi2df = ((t["K"] - t["mu"]) ** 2 / var).sum() / (len(t) - 1)
        auc = roc_auc_score(t["y"], t["p"]) if t["y"].nunique() == 2 else np.nan
        dec = pd.qcut(t["p"].rank(method="first"), 10, labels=False)
        cal = t.groupby(dec).agg(pred=("p", "mean"), obs=("y", "mean"))
        slope = np.polyfit(cal["pred"], cal["obs"], 1)[0] if len(cal) > 2 else np.nan
        brier, brier0 = ((t["p"] - t["y"]) ** 2).mean(), ((t["p0"] - t["y"]) ** 2).mean()
        rows.append({"signature": s, "n": len(t), "event_rate": t["y"].mean(), "AUC": auc, "calibration_slope": slope,
                     "pearson_chi2_df": chi2df, "brier": brier, "brier_fleet_mean": brier0,
                     "beats_baseline": brier < brier0,
                     "pass": bool(auc > 0.65 and 0.8 <= slope <= 1.2 and 0.5 <= chi2df <= 1.5 and brier < brier0),
                     "calibration_by_decile": "; ".join(f"{a:.2f}->{b:.2f}" for a, b in zip(cal["pred"], cal["obs"]))})
    return pd.DataFrame(rows)
