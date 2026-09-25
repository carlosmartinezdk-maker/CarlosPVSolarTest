"""Run the full gas fleet pipeline and write all deliverables to outputs/. Exits 1 if any hard gate FAILs."""
import sys
import numpy as np
import pandas as pd
from config import OUT
from pipeline import scored_panel
import bop
from ledger import build_ledger
import hazard
import reliability as R
import leads
import report
from components import RECOVERY
from economics import cost_table, HORIZON_YR, scale_check


def main(force=False):
    p, kt, curves, cs, cm = scored_panel(force=force, force_bop="--bop" in sys.argv)
    led, ep, lbar = build_ledger(p)
    onset = hazard.onset_hazards(p, ep)
    renewal, _ = hazard.fouling_renewal(p, ep)
    mf = R.model_frame(led, p)
    disp, fits = R.fit_rate_models(mf)
    units = R.unit_frame(p)
    risk = R.risk_table(p, led, ep, lbar, disp, onset, renewal, units)
    risk = R.decision(risk, RECOVERY, cost_table(), HORIZON_YR)
    bt = R.backtest(led, units, disp)
    L = leads.build(p)

    s = p[p["scoreable"]]
    rec = s[s["signature"].isin(["FOULING", "HGP", "COOLING_DEGRADATION", "BOP_INTERMITTENT"])].groupby("signature")["recoverable_mmbtu"].sum()
    fouling_share = rec.get("FOULING", 0) / rec.sum()
    pl = p.drop_duplicates(["plant_id", "cls"])
    nonrec_med = -pl["nonrec_slope_per_yr"].median() * 100

    # deliverables
    report.monthly(p)
    led_out = led.merge(lbar.reset_index(), on="signature", how="left")
    led_out.to_parquet(OUT / "gas_event_ledger.parquet", index=False)
    ep.to_parquet(OUT / "gas_episodes.parquet", index=False)
    report.heat_rate_plot(p, curves, OUT / "heat_rate_curves.png")
    hazard.plot(onset, renewal, OUT / "hazard_curves.png")
    L.to_csv(OUT / "gas_leads.csv", index=False)
    summ = report.plant_summary(p, risk, L, onset, renewal)
    g = report.gates(p, kt, curves, led, disp, onset, renewal, fouling_share, nonrec_med, bt)
    g.loc[len(g)] = {"check": "Scale cross-check: fouling waste scaled to 100 MW & 5% ($/yr)",
                     "expected": "~1.2M (within an order of magnitude)", "got": f"{scale_check(p):,.0f}",
                     "status": "PASS" if 1.2e5 <= scale_check(p) <= 1.2e7 else "WARN",
                     "note": "spec example assumes ~60% CF; fouling plants here run lower"}
    # ---- Part B: balance-of-plant risk index and targeting
    d, ev_year = bop.score(p, cs, cm)
    T = bop.site_targets(p, d, summ)
    C = bop.customer_targets(T)
    yt = bop.yearly_tiers(d, cs, ev_year)
    T.to_csv(OUT / "bop_site_targets.csv", index=False)
    bop.write_customer_targets(C, OUT / "bop_customer_targets.csv")
    n_packs = bop.evidence_pack(p, T, cs, OUT / "bop_evidence_pack")
    yt.to_parquet(OUT / "bop_tiers_by_year.parquet", index=False)
    summ = summ.merge(T[["plant_id", "tech", "BPRI", "bpri_confidence", "tier", "suggested_scope"]]
                      .rename(columns={"tech": "cls", "tier": "bop_tier", "suggested_scope": "bop_suggested_scope"}),
                      on=["plant_id", "cls"], how="left")
    for row in bop.gates(p, cs, cm, T):
        g.loc[len(g)] = row
    assumptions = pd.read_csv(OUT.parent / "inputs" / "assumptions_register.csv")
    with pd.ExcelWriter(OUT / "gas_plant_summary.xlsx", engine="openpyxl") as xw:
        summ.to_excel(xw, sheet_name="plant_summary", index=False)
        L.to_excel(xw, sheet_name="leads", index=False)
        g.to_excel(xw, sheet_name="gates", index=False)
        kt.reset_index().to_excel(xw, sheet_name="k_T", index=False)
        curves.to_excel(xw, sheet_name="reference_curves", index=False)
        pd.concat([onset, renewal]).to_excel(xw, sheet_name="hazards", index=False)
        disp.to_excel(xw, sheet_name="rate_model_dispersion", index=False)
        for sg in R.FAULT_SIGS:
            if sg + "_coef" in fits:
                fits[sg + "_coef"].reset_index(names="term").to_excel(xw, sheet_name=f"rate_{sg}", index=False)
        bt.to_excel(xw, sheet_name="backtest", index=False)
        risk.to_excel(xw, sheet_name="risk_by_signature", index=False)
        lbar.reset_index().to_excel(xw, sheet_name="episode_length", index=False)
        T.to_excel(xw, sheet_name="bop_site_targets", index=False)
        C.to_excel(xw, sheet_name="bop_customer_targets", index=False)
        cost_table().to_excel(xw, sheet_name="remediation_costs", index=False)
        assumptions.to_excel(xw, sheet_name="assumptions", index=False)
    g.to_csv(OUT / "gate_results.csv", index=False)
    report.print_gates(g)
    extras = {"leads": len(L), "tiers": L["conviction_tier"].value_counts().to_dict() if len(L) else {},
              "fouling_share": fouling_share, "nonrec_med": nonrec_med, "L_bar": lbar.round(2).to_dict(),
              "bop_tiers": T["tier"].value_counts().to_dict(), "evidence_briefs": n_packs}
    print(extras)
    return 1 if (g["status"] == "FAIL").any() else 0


if __name__ == "__main__":
    sys.exit(main(force="--force" in sys.argv))
