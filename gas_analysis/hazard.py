"""R3 Weibull hazards per fault signature on two time axes.

A) Onset intensity vs plant state (recurrent events, delayed entry at first observed month):
   axis 'age'  : calendar years since COD
   axis 'eoh'  : cumulative equivalent operating hours since COD (thousands; pre-2019 backlog estimated)
   loglik = sum_events log h(t_e) - sum_units [H(t_exit) - H(t_entry)],  h = (k/eta)(t/eta)^(k-1)
   The EOH-axis likelihood is re-expressed as a density in calendar time (Jacobian: EOH accrual rate at each
   event), so the two AICs are directly comparable.
B) Fouling renewal (gap time since the last detected wash): calendar months vs EOH since wash.
k<1 infant mortality; k~1 random; k>1 wear-out.
"""
import numpy as np
import pandas as pd
from scipy.optimize import minimize

FAULT_SIGS = ["FOULING", "HGP", "CYCLING"]
MIN_EVENTS = 20
K_RANDOM_BAND = (0.9, 1.1)


def _fit(t_entry, t_exit, t_event):
    t_entry = np.maximum(np.asarray(t_entry, float), 0)
    t_exit = np.maximum(np.asarray(t_exit, float), 1e-6)
    t_event = np.maximum(np.asarray(t_event, float), 1e-6)

    def nll(th):
        k, eta = np.exp(th)
        ll = np.sum(np.log(k) - np.log(eta) + (k - 1) * (np.log(t_event) - np.log(eta)))
        ll -= np.sum((t_exit / eta) ** k - (t_entry / eta) ** k)
        return -ll
    x0 = [0.0, np.log(np.median(t_exit))]
    r = minimize(nll, x0, method="Nelder-Mead", options={"maxiter": 4000, "xatol": 1e-6, "fatol": 1e-8})
    k, eta = np.exp(r.x)
    # SE of log k from numerical Hessian
    h = 1e-4
    f0 = r.fun
    fpp = (nll(r.x + [h, 0]) - 2 * f0 + nll(r.x - [h, 0])) / h ** 2
    se_logk = 1 / np.sqrt(fpp) if fpp > 0 else np.nan
    return {"k": k, "eta": eta, "loglik": -r.fun, "k_lo": k * np.exp(-1.96 * se_logk),
            "k_hi": k * np.exp(1.96 * se_logk), "n_events": len(t_event), "n_units": len(t_exit)}


def _shape(k, lo, hi):
    if hi < 1:
        return "infant mortality (k<1)"
    if lo > 1:
        return "wear-out (k>1)"
    return "random (k~1)"


def onset_hazards(p, ep):
    units = p[p["scoreable"] & (p["resp_freq"] == "M") & p["age_yr"].notna()].groupby(["plant_id", "cls"]).agg(
        age_in=("age_yr", "min"), age_out=("age_yr", "max"), eoh_in=("cum_eoh", "min"), eoh_out=("cum_eoh", "max"))
    units = units[(units["age_in"] >= 0)]
    rows, curves = [], []
    for s in FAULT_SIGS:
        e = ep[ep["signature"] == s].merge(units.reset_index()[["plant_id", "cls"]], on=["plant_id", "cls"])
        e = e[e["onset_age_yr"] >= 0]
        if len(e) < MIN_EVENTS:
            rows.append({"signature": s, "axis": "age", "n_events": len(e), "note": "too few events"})
            continue
        a = _fit(units["age_in"], units["age_out"] + 1 / 12, e["onset_age_yr"])
        b = _fit(units["eoh_in"] / 1000, units["eoh_out"] / 1000 + 1e-3, e["onset_cum_eoh"] / 1000)
        b_ll_cal = b["loglik"] + np.log(e["onset_eoh_rate_k_per_yr"].clip(lower=1e-3)).sum()
        for axis, r, llc in [("age", a, a["loglik"]), ("cum_eoh", b, b_ll_cal)]:
            rows.append({"signature": s, "axis": axis, **r, "loglik_calendar_density": llc, "aic": 4 - 2 * llc,
                         "shape": _shape(r["k"], r["k_lo"], r["k_hi"])})
    t = pd.DataFrame(rows)
    if "aic" in t:
        best = t.dropna(subset=["aic"]).sort_values("aic").groupby("signature").head(1)[["signature", "axis"]]
        t = t.merge(best.rename(columns={"axis": "best_axis"}), on="signature", how="left")
    return t


def fouling_renewal(p, ep):
    """Gap time from each detected wash to the next fouling onset (or censoring), in calendar months and in EOH."""
    p = p.sort_values(["plant_id", "cls", "t_idx"])
    fo = ep[ep["signature"] == "FOULING"]
    rows = []
    last_t = p.groupby(["plant_id", "cls"])["t_idx"].max()
    for (pid, cls), d in p[p["wash"]].groupby(["plant_id", "cls"]):
        onsets = np.sort(fo.loc[(fo["plant_id"] == pid) & (fo["cls"] == cls), "start_t"].to_numpy())
        full = p[(p["plant_id"] == pid) & (p["cls"] == cls)]
        tt = full["t_idx"].to_numpy()
        ce = full["eoh"].clip(lower=0).fillna(0).cumsum().to_numpy()
        for tw in d["t_idx"].to_numpy():
            nxt = onsets[onsets > tw]
            end, ev = (nxt[0], 1) if len(nxt) else (last_t[(pid, cls)], 0)
            e0, e1 = ce[tt == tw][0], ce[tt == end][0]
            rate = full.loc[full["t_idx"] == end, "eoh"].clip(lower=1e-3).iat[0] * 12 / 1000
            rows.append({"plant_id": pid, "cls": cls, "months": max(end - tw, 0.5), "eoh_k": max((e1 - e0) / 1000, 1e-3),
                         "event": ev, "rate_k_per_yr": rate})
    g = pd.DataFrame(rows)
    out = []
    if len(g) and g["event"].sum() >= MIN_EVENTS:
        for axis, col, scale in [("months_since_wash", "months", 1 / 12), ("eoh_since_wash", "eoh_k", 1.0)]:
            ev = g[g["event"] == 1]
            r = _fit(np.zeros(len(g)), g[col] * scale, ev[col] * scale)
            llc = r["loglik"] + (np.log(ev["rate_k_per_yr"]).sum() if axis == "eoh_since_wash" else 0)
            out.append({"signature": "FOULING", "axis": axis, **r, "loglik_calendar_density": llc, "aic": 4 - 2 * llc,
                        "shape": _shape(r["k"], r["k_lo"], r["k_hi"])})
    return pd.DataFrame(out), g


def plot(onset, renewal, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    col = {"FOULING": "#2a6fdb", "HGP": "#d9822b", "CYCLING": "#3d9970"}
    fig, axs = plt.subplots(1, 3, figsize=(16, 4.8))
    specs = [("age", "Calendar age since COD (years)", np.linspace(0.5, 60, 200)),
             ("cum_eoh", "Cumulative EOH since COD (thousand hours)", np.linspace(1, 250, 200))]
    for ax, (axis, lab, x) in zip(axs[:2], specs):
        for _, r in onset[onset["axis"] == axis].dropna(subset=["k"]).iterrows():
            h = (r.k / r.eta) * (x / r.eta) ** (r.k - 1)
            ax.plot(x, h, color=col[r.signature], lw=2, label=f"{r.signature}  k={r.k:.2f} [{r.k_lo:.2f},{r.k_hi:.2f}]")
        ax.set_xlabel(lab); ax.set_ylabel("hazard (episodes per unit time)"); ax.set_yscale("log")
        ax.set_title(f"Episode onset hazard vs {axis}"); ax.legend(fontsize=8, frameon=False); ax.grid(alpha=.3)
    ax = axs[2]
    for _, r in renewal.iterrows():
        x = np.linspace(0.05, 3, 200) if r.axis == "months_since_wash" else np.linspace(0.05, 8, 200)
        h = (r.k / r.eta) * (x / r.eta) ** (r.k - 1)
        ax.plot(x, h, lw=2, ls="-" if r.axis == "eoh_since_wash" else "--",
                label=f"{r.axis} ({'k EOH' if r.axis == 'eoh_since_wash' else 'years'})  k={r.k:.2f} [{r.k_lo:.2f},{r.k_hi:.2f}]")
    ax.set_title("Fouling re-onset after a detected wash"); ax.set_xlabel("time since wash (years, or thousand EOH)")
    ax.set_ylabel("hazard"); ax.legend(fontsize=8, frameon=False); ax.grid(alpha=.3)
    fig.suptitle("Weibull hazards by signature, two time axes (monthly EIA-923, 2019-2025)", fontsize=11)
    fig.tight_layout(); fig.savefig(path, dpi=140); plt.close(fig)
