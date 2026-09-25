"""R1/R2 event ledger: duration D (months) vs incidence K (maximal runs, 1-month gap tolerance), explicit exposure."""
import numpy as np
import pandas as pd
from components import LEDGER

GAP_TOL = 1                       # a single intervening month does not break an episode
LEDGER_SIGS = ["FOULING", "HGP", "CYCLING", "NONRECOVERABLE", "DUCT_FIRING", "FUEL_QUALITY", "UNATTRIBUTED",
               "ANNUAL_ONLY", "INTERRUPTIBLE_GAS", "COOLING_DEGRADATION", "BOP_INTERMITTENT"]
FIRM_FULL = 0.999


def _flags(p):
    f = {s: (p["signature"] == s).to_numpy() for s in LEDGER_SIGS if s != "INTERRUPTIBLE_GAS"}
    f["INTERRUPTIBLE_GAS"] = (p["firm_delivery_share"] < FIRM_FULL).fillna(False).to_numpy() & p["scoreable"].to_numpy()
    return f


def episodes(p):
    """One row per maximal run of a signature within a plant x class."""
    p = p.sort_values(["plant_id", "cls", "t_idx"]).reset_index(drop=True)
    flags = _flags(p)
    out = []
    for s, fl in flags.items():
        d = p[fl].copy()
        if d.empty:
            continue
        new_series = (d["plant_id"] != d["plant_id"].shift()) | (d["cls"] != d["cls"].shift())
        brk = new_series | (d["t_idx"].diff() > GAP_TOL + 1)
        d["run"] = brk.cumsum()
        d["eoh_rate"] = d["eoh"].clip(lower=1e-3) * 12 / 1000
        g = d.groupby("run")
        e = g.agg(plant_id=("plant_id", "first"), cls=("cls", "first"), start_t=("t_idx", "min"),
                  end_t=("t_idx", "max"), months=("t_idx", "size"), onset_year=("year", "first"),
                  onset_age_yr=("age_yr", "first"), onset_cum_eoh=("cum_eoh", "first"),
                  onset_eoh_rate_k_per_yr=("eoh_rate", "first"), mean_deficit_pct=("deficit_pct", "mean"),
                  max_deficit_pct=("deficit_pct", "max"), excess_mmbtu=("excess_mmbtu", "sum"),
                  waste_usd=("waste_usd", "sum")).reset_index(drop=True)
        e["signature"] = s
        out.append(e)
    return pd.concat(out, ignore_index=True)


def exposure(p):
    """Exposure months per plant x class x year: months in which a signature could have been detected.
    Monthly-resolved signatures need scoreable monthly-respondent months; ANNUAL_ONLY uses all scoreable months."""
    q = p.assign(em=(p["scoreable"] & (p["resp_freq"] == "M")).astype(int), ea=p["scoreable"].astype(int),
                 om=(p["netgen"] > 0).astype(int))
    e = q.groupby(["plant_id", "cls", "year"])[["em", "ea", "om"]].sum().reset_index()
    return e.rename(columns={"em": "exposure_months", "ea": "exposure_months_all", "om": "operating_months"})


def build_ledger(p):
    p = p.sort_values(["plant_id", "cls", "t_idx"]).reset_index(drop=True)
    ep = episodes(p)
    flags = _flags(p)
    rows = []
    for s, fl in flags.items():
        d = p[fl]
        g = d.groupby(["plant_id", "cls", "year"])
        a = pd.DataFrame({"D": g.size(), "mmbtu_lost": g["excess_mmbtu"].sum(), "usd_lost": g["waste_usd"].sum(),
                          "recoverable_usd": g["recoverable_usd"].sum(), "max_severity_pct": g["deficit_pct"].max()})
        a["signature"] = s
        rows.append(a.reset_index())
    led = pd.concat(rows, ignore_index=True)
    k = ep.groupby(["plant_id", "cls", "onset_year", "signature"]).size().rename("K").reset_index() \
        .rename(columns={"onset_year": "year"})
    ex = exposure(p)
    # full grid: every plant x class x year with exposure, x every signature (zeros matter for rate models)
    grid = ex.merge(pd.DataFrame({"signature": LEDGER_SIGS}), how="cross")
    led = grid.merge(led, on=["plant_id", "cls", "year", "signature"], how="left") \
        .merge(k, on=["plant_id", "cls", "year", "signature"], how="left")
    for c in ["D", "K", "mmbtu_lost", "usd_lost", "recoverable_usd"]:
        led[c] = led[c].fillna(0)
    led["D"] = led["D"].astype(int)
    led["K"] = led["K"].astype(int)
    led["ledger"] = led["signature"].map(LEDGER)
    led = led[(led["exposure_months_all"] > 0) | (led["D"] > 0)]
    lbar = ep.groupby("signature")["months"].sum() / ep.groupby("signature").size()
    return led, ep, lbar.rename("L_bar")
