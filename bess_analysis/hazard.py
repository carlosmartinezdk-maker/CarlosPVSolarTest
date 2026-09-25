"""R3 Weibull onset hazards per fault signature on calendar age vs cumulative EFC (delayed entry, recurrent onsets).
The EFC-axis likelihood is converted to a calendar-time density (Jacobian = EFC accrual rate at each event) so the
AICs compare. k<1 infant mortality, k~1 random, k>1 wear-out."""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

FAULT_SIGS = ["FULL_OUTAGE", "PARTIAL_AVAILABILITY", "THERMAL_AUX", "UNATTRIBUTED"]
MIN_EVENTS = 15


def _fit(t_in, t_out, t_ev):
    t_in = np.maximum(np.asarray(t_in, float), 0)
    t_out = np.maximum(np.asarray(t_out, float), 1e-6)
    t_ev = np.maximum(np.asarray(t_ev, float), 1e-6)

    def nll(th):
        k, eta = np.exp(th)
        return -(np.sum(np.log(k) - np.log(eta) + (k - 1) * (np.log(t_ev) - np.log(eta)))
                 - np.sum((t_out / eta) ** k - (t_in / eta) ** k))
    r = minimize(nll, [0.0, np.log(np.median(t_out))], method="Nelder-Mead", options={"maxiter": 4000})
    h = 1e-4
    fpp = (nll(r.x + [h, 0]) - 2 * r.fun + nll(r.x - [h, 0])) / h ** 2
    se = 1 / np.sqrt(fpp) if fpp > 0 else np.nan
    k, eta = np.exp(r.x)
    return {"k": k, "eta": eta, "loglik": -r.fun, "k_lo": k * np.exp(-1.96 * se), "k_hi": k * np.exp(1.96 * se),
            "n_events": len(t_ev), "n_units": len(t_out)}


def _shape(lo, hi):
    return "infant mortality (k<1)" if hi < 1 else ("wear-out (k>1)" if lo > 1 else "random (k~1)")


def onset_hazards(p, ep):
    s = p[p["in_service"] & (p["resp_freq"] == "M") & p["age_yr"].notna()]
    u = s.groupby("plant_id").agg(a0=("age_yr", "min"), a1=("age_yr", "max"), e0=("cum_efc", "min"), e1=("cum_efc", "max"))
    u = u[u["a0"] >= -0.1]
    rows = []
    for sig in FAULT_SIGS:
        e = ep[(ep["signature"] == sig) & ep["plant_id"].isin(u.index) & (ep["onset_age_yr"] >= 0)]
        if len(e) < MIN_EVENTS:
            rows.append({"signature": sig, "axis": "age", "n_events": len(e), "note": "too few events"})
            continue
        a = _fit(u["a0"].clip(lower=0), u["a1"] + 1 / 12, e["onset_age_yr"])
        b = _fit(u["e0"] / 100, u["e1"] / 100 + 1e-3, e["onset_cum_efc"] / 100)
        rate = (e["onset_efc_rate"].fillna(0).clip(lower=0.01) * 12 / 100)
        llb = b["loglik"] + np.log(rate).sum()
        for axis, r, ll in [("age_years", a, a["loglik"]), ("cum_efc_x100", b, llb)]:
            rows.append({"signature": sig, "axis": axis, **r, "loglik_calendar_density": ll, "aic": 4 - 2 * ll,
                         "shape": _shape(r["k_lo"], r["k_hi"])})
    t = pd.DataFrame(rows)
    if "aic" in t:
        best = t.dropna(subset=["aic"]).sort_values("aic").groupby("signature").head(1)[["signature", "axis"]]
        t = t.merge(best.rename(columns={"axis": "best_axis"}), on="signature", how="left")
    return t


def plot(t, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"FULL_OUTAGE": "#d9534f", "PARTIAL_AVAILABILITY": "#d9822b", "THERMAL_AUX": "#2a6fdb", "UNATTRIBUTED": "#6b7a8f"}
    fig, axs = plt.subplots(1, 2, figsize=(13, 4.6))
    for ax, axis, lab, x in [(axs[0], "age_years", "age since COD (years)", np.linspace(0.05, 12, 200)),
                             (axs[1], "cum_efc_x100", "cumulative equivalent full cycles (x100)", np.linspace(0.05, 30, 200))]:
        for _, r in t[(t["axis"] == axis)].dropna(subset=["k"]).iterrows():
            ax.plot(x, (r.k / r.eta) * (x / r.eta) ** (r.k - 1), color=col.get(r.signature), lw=2,
                    label=f"{r.signature}  k={r.k:.2f} [{r.k_lo:.2f},{r.k_hi:.2f}]")
        ax.set_yscale("log"); ax.set_xlabel(lab); ax.set_ylabel("onset hazard"); ax.grid(alpha=.3)
        ax.legend(fontsize=8, frameon=False)
    fig.suptitle("BESS fault-episode onset hazards: calendar age vs throughput", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)
