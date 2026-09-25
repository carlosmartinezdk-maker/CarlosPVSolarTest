"""R4 negative-binomial rate model, R5 credibility shrinkage, R6 P(12mo) and expected annual loss in MWh, R7 backtest."""
import warnings
import numpy as np
import pandas as pd
import statsmodels.api as sm
import statsmodels.formula.api as smf
from sklearn.metrics import roc_auc_score
from hazard import FAULT_SIGS

POOL_MIN_UNITS = 5
POOL_MIN_EXPOSURE = 60
LAM_FLOOR = 1e-4
BACKTEST_YEARS = [2022, 2023, 2024]
TOP_BA = 8
FORMULA = ("K ~ C(dur_band) + log_age + log_cefc + C(chem_g) + C(enclosure_g) + arb + freq + C(ba_g) "
           "+ C(climate_region) + C(vintage_g) + hybrid")


def unit_frame(p, regions):
    last = p.sort_values("t_idx").groupby("plant_id").last()
    u = last[["dur_band", "chem", "enclosure", "ba", "cod_year", "hybrid", "nameplate_mw", "e_rated_mwh", "Arbitrage",
              "Frequency Regulation"]].reset_index()
    u = u.merge(regions, on="plant_id", how="left")
    top = u["ba"].value_counts().index[:TOP_BA]
    u["ba_g"] = np.where(u["ba"].isin(top), u["ba"], "other")
    u["chem_g"] = np.where(u["chem"] == "LIB", "LIB", "other")
    u["enclosure_g"] = u["enclosure"].fillna("NA").where(u["enclosure"].isin(["CS", "BL", "CT"]), "other")
    u["vintage_g"] = pd.cut(u["cod_year"].fillna(2020), [0, 2019.5, 2021.5, 2023.5, 3000],
                            labels=["<=2019", "2020-21", "2022-23", "2024+"]).astype(str)
    u["arb"] = (u["Arbitrage"] == "Y").astype(int)
    u["freq"] = (u["Frequency Regulation"] == "Y").astype(int)
    u["climate_region"] = u["climate_region"].fillna("inland")
    u["hybrid"] = u["hybrid"].astype(int)
    return u


def model_frame(led, p, units):
    yr = p.groupby(["plant_id", "year"]).agg(age=("age_yr", "mean"), cefc=("cum_efc", "max")).reset_index()
    d = led[led["signature"].isin(FAULT_SIGS) & (led["exposure_months"] > 0)].merge(yr, on=["plant_id", "year"], how="left") \
        .merge(units, on="plant_id", how="left")
    d["log_age"] = np.log1p(d["age"].clip(lower=0).fillna(0))
    d["log_cefc"] = np.log1p(d["cefc"].fillna(0) / 100)
    d["dur_band"] = d["dur_band"].fillna("nan")
    return d


def fit_rate_models(mf):
    rows, coefs = [], {}
    for s in FAULT_SIGS:
        d = mf[mf["signature"] == s]
        vm = d.loc[d["exposure_months"] >= 6, "K"]
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            pois = smf.glm(FORMULA, d, family=sm.families.Poisson(), offset=np.log(d["exposure_months"])).fit()
            try:
                nb = smf.negativebinomial(FORMULA, d, offset=np.log(d["exposure_months"])).fit(disp=0, maxiter=500)
                alpha, ll = float(nb.params["alpha"]), nb.llf
                c = nb.params.drop("alpha")
                coefs[s] = pd.DataFrame({"coef": c, "se": nb.bse.drop("alpha"), "rate_ratio": np.exp(c),
                                         "p": nb.pvalues.drop("alpha")})
            except Exception:
                alpha, ll = np.nan, np.nan
        rows.append({"signature": s, "plant_years": len(d), "events": int(d["K"].sum()),
                     "var_mean_ratio": vm.var() / vm.mean() if vm.mean() > 0 else np.nan,
                     "poisson_pearson_disp": pois.pearson_chi2 / pois.df_resid, "nb_alpha": alpha,
                     "phi": 1 / alpha if alpha and alpha > 1e-3 else np.inf,
                     "lr_nb_vs_poisson": 2 * (ll - pois.llf),
                     "model_used": "negative binomial" if alpha and alpha > 1e-3 else "poisson (alpha~0)"})
    return pd.DataFrame(rows), coefs


def _pool(tab, keys):
    g = tab.groupby(keys).agg(K=("K", "sum"), E=("exposure_months", "sum"), n=("plant_id", "nunique"))
    g = g[(g["n"] >= POOL_MIN_UNITS) & (g["E"] >= POOL_MIN_EXPOSURE)]
    return (g["K"] / g["E"]).rename("lam")


def shrink(ls, units, phi):
    own = ls.groupby("plant_id").agg(K_own=("K", "sum"), E_own=("exposure_months", "sum")).reset_index().merge(units, on="plant_id", how="left")
    tab = ls.merge(units, on="plant_id", how="left")
    own["lam_pool"], own["pool_level"] = np.nan, ""
    for keys in [["ba_g", "dur_band", "vintage_g"], ["dur_band", "climate_region"], ["dur_band"]]:
        r = _pool(tab, keys)
        m = own["lam_pool"].isna()
        own.loc[m, "lam_pool"] = own.loc[m, keys].merge(r.reset_index(), on=keys, how="left")["lam"].to_numpy()
        own.loc[m & own["lam_pool"].notna(), "pool_level"] = "+".join(keys)
    m = own["lam_pool"].isna()
    own.loc[m, "lam_pool"] = tab["K"].sum() / max(tab["exposure_months"].sum(), 1)
    own.loc[m, "pool_level"] = "fleet"
    lp = own["lam_pool"].clip(lower=LAM_FLOOR)
    tau = phi / lp if np.isfinite(phi) else pd.Series(np.inf, index=own.index)
    own["Z"] = np.where(np.isfinite(tau), own["E_own"] / (own["E_own"] + tau), 0.0)
    own["lam_hat"] = (own["Z"] * own["K_own"] / own["E_own"].clip(lower=1) + (1 - own["Z"]) * lp).clip(lower=LAM_FLOOR)
    return own


def p12(lam, phi):
    return 1 - np.exp(-lam * 12) if not np.isfinite(phi) else 1 - (1 + lam * 12 / phi) ** (-phi)


def risk_table(p, led, ep, lbar, disp, units, hz):
    recent = p[(p["t_idx"] > p["t_idx"].max() - 12) & p["in_service"]]
    typ = recent.groupby("plant_id")["discharge"].median().rename("typical_monthly_discharge_mwh")
    delta = (ep.assign(d=ep["mwh_at_stake"] / (ep["months"] * ep["typical_discharge"].clip(lower=1)))
             .groupby("signature")["d"].median().clip(upper=1.0))
    out = []
    for s in FAULT_SIGS:
        phi = float(disp.loc[disp["signature"] == s, "phi"].iat[0])
        o = shrink(led[led["signature"] == s], units, phi).merge(typ.reset_index(), on="plant_id", how="left")
        o["signature"], o["phi"] = s, phi
        o["P12"] = p12(o["lam_hat"], phi)
        o["L_bar_months"] = lbar.get(s, np.nan)
        o["delta_bar"] = delta.get(s, np.nan)
        o["EAL_MWh"] = o["lam_hat"] * 12 * o["L_bar_months"] * o["delta_bar"] * o["typical_monthly_discharge_mwh"]
        b = hz[(hz["signature"] == s) & hz.get("k", pd.Series(dtype=float)).notna()].sort_values("aic") if "aic" in hz else pd.DataFrame()
        o["hazard_axis"] = b["axis"].iat[0] if len(b) else None
        o["hazard_shape"] = b["shape"].iat[0] if len(b) else None
        out.append(o)
    return pd.concat(out, ignore_index=True)


def backtest(led, units, disp):
    rows = []
    for s in FAULT_SIGS:
        phi = float(disp.loc[disp["signature"] == s, "phi"].iat[0])
        ls = led[led["signature"] == s]
        preds = []
        for y in BACKTEST_YEARS:
            tr, te = ls[ls["year"] <= y], ls[(ls["year"] == y + 1) & (ls["exposure_months"] > 0)]
            fleet = max(tr["K"].sum() / max(tr["exposure_months"].sum(), 1), LAM_FLOOR)
            t = te.merge(shrink(tr, units, phi)[["plant_id", "lam_hat"]], on="plant_id", how="left")
            t["new_site"] = t["lam_hat"].isna()
            t["lam_hat"] = t["lam_hat"].fillna(fleet)
            f = (lambda mu: 1 - (1 + mu / phi) ** (-phi)) if np.isfinite(phi) else (lambda mu: 1 - np.exp(-mu))
            t["mu"], t["mu0"] = t["lam_hat"] * t["exposure_months"], fleet * t["exposure_months"]
            t["p"], t["p0"], t["y"] = f(t["mu"]), f(t["mu0"]), (t["K"] > 0).astype(int)
            preds.append(t)
        t = pd.concat(preds)
        var = t["mu"] + (t["mu"] ** 2 / phi if np.isfinite(phi) else 0)
        chi = ((t["K"] - t["mu"]) ** 2 / var).sum() / (len(t) - 1)
        auc = roc_auc_score(t["y"], t["p"]) if t["y"].nunique() == 2 else np.nan
        cal = t.groupby(pd.qcut(t["p"].rank(method="first"), 10, labels=False)).agg(pred=("p", "mean"), obs=("y", "mean"))
        slope = np.polyfit(cal["pred"], cal["obs"], 1)[0]
        b, b0 = ((t["p"] - t["y"]) ** 2).mean(), ((t["p0"] - t["y"]) ** 2).mean()
        rows.append({"signature": s, "n": len(t), "share_new_sites": t["new_site"].mean(), "event_rate": t["y"].mean(),
                     "AUC": auc, "calibration_slope": slope, "pearson_chi2_df": chi, "brier": b, "brier_fleet_mean": b0,
                     "beats_baseline": b < b0,
                     "pass": bool(auc > 0.65 and 0.8 <= slope <= 1.2 and 0.5 <= chi <= 1.5 and b < b0)})
    return pd.DataFrame(rows)
