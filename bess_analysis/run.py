"""Run the BESS pipeline end to end; writes outputs/ and exits 1 if a hard gate FAILs."""
import sys
import pandas as pd
from config import OUT, CACHE
from panel import build
import efficiency_decomp as E
import peers
import signatures as S
import ledger
import hazard
import reliability as R
import leads
import report


def main(force=False):
    p = build(force=force)
    p = peers.add_uti(p)
    dec, rolls = E.decompose(p)
    dec = dec.merge(p.drop_duplicates("plant_id")[["plant_id", "hybrid"]], on="plant_id", how="left")
    fd, _ = S.fade(p)
    p = S.assign(p, dec, fd)
    led, ep, lbar = ledger.build_ledger(p)
    hz = hazard.onset_hazards(p, ep)
    reg = pd.read_parquet(CACHE / "climate_regions.parquet")[["plant_id", "climate_region"]] \
        if (CACHE / "climate_regions.parquet").exists() else pd.DataFrame({"plant_id": [], "climate_region": []})
    units = R.unit_frame(p, reg)
    disp, coefs = R.fit_rate_models(R.model_frame(led, p, units))
    risk = R.risk_table(p, led, ep, lbar, disp, units, hz)
    bt = R.backtest(led, units, disp)
    L = leads.build(p)

    report.monthly(p)
    d = report.decomposition_csv(dec, p)
    report.decomposition_plot(d, OUT / "efficiency_decomposition.png")
    led.merge(lbar.reset_index(), on="signature", how="left").to_parquet(OUT / "bess_event_ledger.parquet", index=False)
    ep.to_parquet(OUT / "bess_episodes.parquet", index=False)
    hazard.plot(hz, OUT / "hazard_curves.png")
    L.to_csv(OUT / "bess_leads.csv", index=False)
    report.gates(p, d)
    g = report.reliability_gates(disp, bt)
    summ = report.site_summary(p, dec, fd, risk, L)
    quarantine = p.drop_duplicates("plant_id")
    quarantine = quarantine[quarantine["hybrid"]][["plant_id", "plant_name", "state", "hybrid_reasons"]]
    quarantine.to_csv(OUT / "hybrid_quarantine.csv", index=False)
    with pd.ExcelWriter(OUT / "bess_site_summary.xlsx", engine="openpyxl") as xw:
        summ.to_excel(xw, sheet_name="site_summary", index=False)
        L.to_excel(xw, sheet_name="leads", index=False)
        g.to_excel(xw, sheet_name="gates", index=False)
        d.to_excel(xw, sheet_name="efficiency_decomposition", index=False)
        hz.to_excel(xw, sheet_name="hazards", index=False)
        disp.to_excel(xw, sheet_name="rate_model_dispersion", index=False)
        for s, c in coefs.items():
            c.reset_index(names="term").to_excel(xw, sheet_name=f"rate_{s[:20]}", index=False)
        bt.to_excel(xw, sheet_name="backtest", index=False)
        risk.to_excel(xw, sheet_name="risk_by_signature", index=False)
        lbar.reset_index().to_excel(xw, sheet_name="episode_length", index=False)
        quarantine.to_excel(xw, sheet_name="hybrid_quarantine", index=False)
        pd.read_csv(OUT.parent / "inputs" / "assumptions_register.csv").to_excel(xw, sheet_name="assumptions", index=False)
    g.to_csv(OUT / "gate_results.csv", index=False)
    report.print_gates(g)
    sc = p[p["in_service"] & (p["resp_freq"] == "M")]
    print("signatures (scored, standalone):", sc[~sc["hybrid"]]["signature"].value_counts().to_dict())
    print("leads:", len(L), L["conviction_tier"].value_counts().to_dict() if len(L) else {})
    print("hazards:\n", hz[["signature", "axis", "k", "k_lo", "k_hi", "aic", "shape"]].round(3).to_string())
    print("dispersion:\n", disp.round(3).to_string())
    print("backtest:\n", bt.round(3).to_string())
    return 1 if (g["status"] == "FAIL").any() else 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
