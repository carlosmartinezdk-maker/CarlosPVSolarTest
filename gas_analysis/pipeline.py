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


def scored_panel(force=False):
    f = CACHE / "panel_scored.parquet"
    if f.exists() and not force:
        return pd.read_parquet(f), pd.read_parquet(CACHE / "kt.parquet"), pd.read_parquet(CACHE / "curves.parquet")
    p = build(force=force)
    p = temperature.attach_temps(p)
    kt = temperature.fit_kt(p)
    p = temperature.correct(p, kt)
    curves = reference.fit_curves(p)
    p = reference.add_indices(p, curves)
    p = peers.add_pri(p)
    p = economics.attach_fuel_cost(p, fuel_cost.load())
    p = components.assign(p)
    p = economics.add_excess(p)
    p.to_parquet(f, index=False)
    kt.to_parquet(CACHE / "kt.parquet")
    curves.to_parquet(CACHE / "curves.parquet", index=False)
    return p, kt, curves


if __name__ == "__main__":
    import time
    t = time.time()
    p, kt, curves = scored_panel(force=True)
    print("built in %.0fs" % (time.time() - t), p.shape)
    s = p[p["scoreable"]]
    print(s.groupby("cls")["signature"].value_counts(normalize=True).unstack().round(3).T)
    rec = s[s["signature"].isin(["FOULING", "HGP"])].groupby("signature")["recoverable_mmbtu"].sum()
    print("recoverable MMBtu by component:", rec.round(-3).to_dict(), "fouling share:", (rec.get("FOULING", 0) / rec.sum()).round(3))
    pl = p.drop_duplicates(["plant_id", "cls"])
    print("non-recoverable slope median (%/yr, degradation positive):",
          (-pl["nonrec_slope_per_yr"].median() * 100).round(3), "n=", pl["nonrec_slope_per_yr"].notna().sum())
    print("wash events:", int(p["wash"].sum()), "scale check $/yr (100MW,5%):", round(economics.scale_check(p), -3))
