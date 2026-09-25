"""M5 temperature correction: k_T per class, fitted within load-factor bands (and within plant)."""
import numpy as np
import pandas as pd
from weather import plant_monthly_temps

T_REF_C = 15.0
LF_BAND_EDGES = np.array([0.02, 0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.1])
# Hinge form: below ISO 15 degC the monthly response is ~0 (inlet heating / IGV control), so a symmetric linear
# k_T fits ~0 and would "correct" winter months the wrong way. Fitted and applied on max(T - 15, 0).
HINGE = True
KT_EXPECT = {"CC": (0.0, 0.002), "GT": (0.001, 0.003), "ST": (0.0, 0.003), "IC": (0.0, 0.003)}   # spec: SC 0.1-0.3%/C, CC less
KT_MIN_N = 500


def attach_temps(p):
    t = plant_monthly_temps(p["plant_id"].unique())
    p = p.drop(columns=[c for c in ["t_amb_c", "t_source"] if c in p.columns])
    p = p.merge(t, on=["plant_id", "year", "month"], how="left")
    return p


def _tx(t):
    return np.maximum(t - T_REF_C, 0.0) + T_REF_C if HINGE else t


def lf_band(lf):
    return pd.cut(lf, LF_BAND_EDGES, labels=False, include_lowest=True)


def fit_kt(p):
    """log(HR) = FE(plant x LF band) + b*T ; k_T = exp(b)-1. Fitted on non-CHP, QC-ok, scoreable months."""
    rows = []
    for cls, d in p.groupby("cls"):
        d = d[(d["qc_hr"] == "ok") & ~d["chp_cohort"] & d["t_amb_c"].notna() & (d["lf"] >= LF_BAND_EDGES[0])
              & (d["lf"] <= LF_BAND_EDGES[-1])].copy()
        d["band"] = lf_band(d["lf"])
        d["g"] = d["plant_id"].astype(str) + "_" + d["band"].astype(str)
        d["y"] = np.log(d["hr"])
        d["t_amb_c"] = _tx(d["t_amb_c"])
        # also control LF within band linearly
        for c in ["y", "t_amb_c", "lf"]:
            d[c + "_dm"] = d[c] - d.groupby("g")[c].transform("mean")
        n = d.groupby("g")["y"].transform("size")
        d = d[n >= 3]
        X = d[["t_amb_c_dm", "lf_dm"]].values
        beta, *_ = np.linalg.lstsq(X, d["y_dm"].values, rcond=None)
        resid = d["y_dm"].values - X @ beta
        dof = len(d) - d["g"].nunique() - 2
        se = np.sqrt((resid @ resid) / dof * np.linalg.inv(X.T @ X)[0, 0])
        kt = np.expm1(beta[0])
        lo, hi = KT_EXPECT[cls]
        rows.append({"cls": cls, "k_T_per_C": kt, "se": se, "n": len(d), "groups": d["g"].nunique(),
                     "sign_ok": kt > 0, "in_expected_range": lo <= kt <= hi})
    return pd.DataFrame(rows).set_index("cls")


def correct(p, kt):
    k = p["cls"].map(kt["k_T_per_C"]).fillna(0.0)
    t = _tx(p["t_amb_c"].fillna(T_REF_C))          # no temperature -> no correction (flagged in qc_flags)
    p["hr_corr"] = p["hr"] / (1 + k * (t - T_REF_C))
    return p


if __name__ == "__main__":
    from heat_rate import build
    p = attach_temps(build())
    print("temp coverage:", p["t_amb_c"].notna().mean().round(4), p["t_source"].value_counts(dropna=False).to_dict())
    print(fit_kt(p))
