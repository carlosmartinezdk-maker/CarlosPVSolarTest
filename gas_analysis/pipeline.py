"""End-to-end build of the scored monthly panel (cached)."""
import pandas as pd
from config import CACHE
from heat_rate import build
import temperature
import reference
import peers
import fuel_cost
import economics
import components
import bop
from climate import regions


def bop_layer(p):
    """Part B signatures (COOLING_DEGRADATION, BOP_INTERMITTENT) on top of the base signature assignment.
    Needs climate region (cooling peer group), EIA-860 cooling type and CEMS cycling exposure."""
    p = p.drop(columns=[c for c in ["climate_region"] if c in p.columns])
    p = p.merge(regions()[["plant_id", "climate_region"]], on="plant_id", how="left")
    cm = bop.cems_plant_metrics(p)
    heavy = bop.heavy_cycling_set(bop.exposure_frame(p, cm))
    p, cs, bi = components.add_bop_signatures(p, bop.cooling_types(), heavy)
    return p, cs, cm


def scored_panel(force=False, force_bop=False):
    """Returns (panel, k_T, curves, cooling_signal_table, cems_plant_metrics). The expensive base panel is cached
    separately so the BoP layer can be re-run when CEMS data is added."""
    f = CACHE / "panel_scored.parquet"
    fb = CACHE / "panel_base.parquet"
    if f.exists() and not (force or force_bop):
        return (pd.read_parquet(f), pd.read_parquet(CACHE / "kt.parquet"), pd.read_parquet(CACHE / "curves.parquet"),
                pd.read_parquet(CACHE / "cooling_signal.parquet"), pd.read_parquet(CACHE / "cems_plant.parquet"))
    if fb.exists() and not force:
        p = pd.read_parquet(fb)
    else:
        p = base_panel(force)
    p, cs, cm = bop_layer(p)
    p = economics.add_excess(p)
    p.to_parquet(f, index=False)
    cs.to_parquet(CACHE / "cooling_signal.parquet", index=False)
    cm.to_parquet(CACHE / "cems_plant.parquet", index=False)
    return p, pd.read_parquet(CACHE / "kt.parquet"), pd.read_parquet(CACHE / "curves.parquet"), cs, cm


def base_panel(force=False):
    p = build(force=force)
    p = temperature.attach_temps(p)
    kt = temperature.fit_kt(p)
    p = temperature.correct(p, kt)
    curves = reference.fit_curves(p)
    p = reference.add_indices(p, curves)
    p = peers.add_pri(p)
    p = economics.attach_fuel_cost(p, fuel_cost.load())
    p = components.assign(p)
    p.to_parquet(CACHE / "panel_base.parquet", index=False)
    kt.to_parquet(CACHE / "kt.parquet")
    curves.to_parquet(CACHE / "curves.parquet", index=False)
    return p


if __name__ == "__main__":
    import time
    t = time.time()
    p, kt, curves, cs, cm = scored_panel(force=True)
    print("built in %.0fs" % (time.time() - t), p.shape)
    s = p[p["scoreable"]]
    print(s.groupby("cls")["signature"].value_counts(normalize=True).unstack().round(3).T)
    rec = s[s["signature"].isin(["FOULING", "HGP", "COOLING_DEGRADATION", "BOP_INTERMITTENT"])].groupby("signature")["recoverable_mmbtu"].sum()
    print("recoverable MMBtu by component:", rec.round(-3).to_dict(), "fouling share:", (rec.get("FOULING", 0) / rec.sum()).round(3))
    pl = p.drop_duplicates(["plant_id", "cls"])
    print("non-recoverable slope median (%/yr, degradation positive):",
          (-pl["nonrec_slope_per_yr"].median() * 100).round(3), "n=", pl["nonrec_slope_per_yr"].notna().sum())
    print("wash events:", int(p["wash"].sum()), "scale check $/yr (100MW,5%):", round(economics.scale_check(p), -3))
