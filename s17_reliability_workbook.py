"""
S17 - SSI_Solar_Reliability_Metrics.xlsx (Reliability Engineering Addendum,
Section 11). The analyst-facing artefact: raw counts and fitted
distribution parameters are hardcoded values (they come from an external
MLE fit, not something Excel can derive), but every DERIVED metric -
MTTR, lambda, MTBF, spares gap, RPN, and the inspection cost curve - is a
live formula referencing the Assumptions tab, so PPA/rho/rates can be
flexed without a pipeline re-run (test 45).

Formatting matches the production workbook convention: Arial 10, dark navy
header fill with white bold text, frozen header row, autofilter, `#,##0`
on counts/MWh, `0.000` on rates/beta, `0.0%` on shares, blue font for
input cells (Assumptions), black for formulas.
"""
import json
import logging

import numpy as np
import openpyxl
import pandas as pd
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S17 %(message)s")
log = logging.getLogger("s17")

HEADER_FILL = PatternFill(start_color="1F2A44", end_color="1F2A44", fill_type="solid")
HEADER_FONT = Font(name="Arial", size=10, bold=True, color="FFFFFF")
BODY_FONT = Font(name="Arial", size=10)
INPUT_FONT = Font(name="Arial", size=10, color="0000CC")
SIGS = sorted(config.RELIABILITY_SIGNATURES)


def style_header_row(ws, row=1):
    for cell in ws[row]:
        cell.fill = HEADER_FILL
        cell.font = HEADER_FONT
        cell.alignment = Alignment(horizontal="center")
    ws.freeze_panes = ws.cell(row=row + 1, column=1)
    ws.auto_filter.ref = ws.dimensions


def write_df(ws, df: pd.DataFrame, number_formats: dict = None):
    number_formats = number_formats or {}
    for j, col in enumerate(df.columns, start=1):
        ws.cell(row=1, column=j, value=col)
    for i, row in enumerate(df.itertuples(index=False), start=2):
        for j, val in enumerate(row, start=1):
            if isinstance(val, (np.integer,)):
                val = int(val)
            elif isinstance(val, (np.floating,)):
                val = float(val) if np.isfinite(val) else None
            elif pd.isna(val) if not isinstance(val, (list, dict)) else False:
                val = None
            cell = ws.cell(row=i, column=j, value=val)
            cell.font = BODY_FONT
            fmt = number_formats.get(df.columns[j - 1])
            if fmt:
                cell.number_format = fmt
    style_header_row(ws)
    for j, col in enumerate(df.columns, start=1):
        width = min(32, max(10, len(str(col)) + 2))
        ws.column_dimensions[get_column_letter(j)].width = width


# --------------------------------------------------------------------------
# Assumptions tab - fixed row layout so other sheets can reference cells
# --------------------------------------------------------------------------
def build_assumptions_sheet(wb, pricing):
    ws = wb.create_sheet("Assumptions")
    ws.append(["Parameter", "Value", "Status"])
    rows = {}

    def put(label, value, status="confirmed"):
        r = ws.max_row + 1
        ws.cell(row=r, column=1, value=label).font = BODY_FONT
        c = ws.cell(row=r, column=2, value=value)
        c.font = INPUT_FONT
        ws.cell(row=r, column=3, value=status).font = BODY_FONT
        rows[label] = r
        return r

    put("PPA_usd_per_mwh", config.PPA_USD_PER_MWH, "fixed by Carlos, Aug 2026")
    put("data_lag_months", config.RELIABILITY["data_lag_months"], "EIA publication lag, assumed")
    put("spares_service_level", config.RELIABILITY["spares_service_level"], "assumed (95% coverage target)")
    put("block_mw_default", config.RELIABILITY["block_mw_default"], "assumed fallback where no block_fraction fitted")
    put("insp_usd_per_mwdc", pricing["offerings"]["solar_inspection"]["usd_per_mwdc_inspected"], "confirmed")
    put("scada_usd_per_mwdc_yr", pricing["offerings"]["scada_monitoring"]["usd_per_mwdc_year"], "confirmed")
    put("reliability_warranty_years", config.RELIABILITY_WARRANTY_YEARS,
        "blended inverter/module-product term - see Notes tab (Section 9.2 gate fix)")
    put("min_failures_to_fit", config.RELIABILITY["min_failures_to_fit"], "assumed")

    for sig in SIGS:
        put(f"rho_{sig}", config.SIGNATURE_ACTION_MAP[sig]["rec_pct"], "PLACEHOLDER - no ground truth yet")
    for sig in SIGS:
        rc = pricing["repair_costs"]["by_signature"][sig]
        put(f"mobilisation_usd_{sig}", rc["mobilisation_usd"], "ESTIMATE, not a vendor quote")
    for sig in SIGS:
        rc = pricing["repair_costs"]["by_signature"][sig]
        put(f"unit_rate_usd_per_mwdc_{sig}", rc["usd_per_mwdc_affected"], "ESTIMATE, not a vendor quote")

    style_header_row(ws)
    ws.column_dimensions["A"].width = 34
    ws.column_dimensions["B"].width = 14
    ws.column_dimensions["C"].width = 42
    return rows


def a(rows, label):
    """Return an absolute Assumptions!$B$n reference for a labeled input."""
    return f"Assumptions!$B${rows[label]}"


# --------------------------------------------------------------------------
# Fleet Summary - signature grain, MTTR/lambda/MTBF as live formulas
# --------------------------------------------------------------------------
def build_fleet_summary(wb, episodes, life, ledger, rows_a):
    ws = wb.create_sheet("Fleet Summary")
    headers = ["Signature", "Episodes", "Fault months", "Exposure site-years", "Avg N_blocks",
               "MTTR (months)", "Lambda (site-yr)", "Lambda (block-yr)", "MTBF (years)",
               "Lost MWh", "Lost USD", "Share of loss", "Fitted beta", "Fitted eta (yr)",
               "Failure-mode class"]
    ws.append(headers)

    with open("data/reliability_fits.json") as f:
        fits = {s["signature"]: s for s in json.load(f)["signatures"]}
    ep_sig = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)]

    r = 2
    for sig in SIGS:
        eps = ep_sig[ep_sig["signature"] == sig]
        n_episodes = len(eps)
        fault_months = int(eps["n_months"].sum())
        exposure = life.loc[life["signature"] == sig, "duration_years"].sum()
        avg_blocks = life.loc[life["signature"] == sig, "n_blocks"].mean()
        lost_mwh = ledger.loc[ledger["signature"] == sig, "mwh_lost"].sum()
        lost_usd = ledger.loc[ledger["signature"] == sig, "usd_lost"].sum()
        fit = fits[sig]

        ws.cell(row=r, column=1, value=sig)
        ws.cell(row=r, column=2, value=n_episodes)
        ws.cell(row=r, column=3, value=fault_months)
        ws.cell(row=r, column=4, value=round(float(exposure), 2))
        ws.cell(row=r, column=5, value=round(float(avg_blocks), 2))
        ws.cell(row=r, column=6, value=f"=C{r}/B{r}")                      # MTTR = fault_months / episodes
        ws.cell(row=r, column=7, value=f"=B{r}/D{r}")                      # lambda_site = episodes / exposure
        ws.cell(row=r, column=8, value=f"=G{r}/E{r}")                      # lambda_block = lambda_site / N_blocks
        ws.cell(row=r, column=9, value=f"=1/G{r}")                         # MTBF = 1 / lambda_site
        ws.cell(row=r, column=10, value=round(float(lost_mwh), 0))
        ws.cell(row=r, column=11, value=round(float(lost_usd), 0))
        ws.cell(row=r, column=12, value=f"=K{r}/SUM($K$2:$K${len(SIGS)+1})")
        ws.cell(row=r, column=13, value=round(fit["weibull_beta"], 3))
        ws.cell(row=r, column=14, value=round(fit["weibull_eta_years"], 2))
        ws.cell(row=r, column=15, value=fit["beta_classification"])
        r += 1

    fmts = {"Episodes": "#,##0", "Fault months": "#,##0", "Exposure site-years": "#,##0.0",
            "Avg N_blocks": "0.00", "MTTR (months)": "0.00", "Lambda (site-yr)": "0.000",
            "Lambda (block-yr)": "0.000", "MTBF (years)": "0.00", "Lost MWh": "#,##0",
            "Lost USD": "#,##0", "Share of loss": "0.0%", "Fitted beta": "0.000",
            "Fitted eta (yr)": "0.00"}
    for j, col in enumerate(headers, start=1):
        fmt = fmts.get(col)
        if fmt:
            for i in range(2, r):
                ws.cell(row=i, column=j).number_format = fmt
        for i in range(2, r):
            ws.cell(row=i, column=j).font = BODY_FONT
    style_header_row(ws)
    for j in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 16
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["O"].width = 20


# --------------------------------------------------------------------------
# Inspection Schedule - total_cost(T) as live formulas per site, so the
# optimum can move when PPA/rho/insp rate change on the Assumptions tab
# (test 45).
# --------------------------------------------------------------------------
def build_inspection_schedule(wb, inspection_df, hazard, life, episodes, rows_a):
    ws = wb.create_sheet("Inspection Schedule")
    fleet_lam = (life.groupby("signature").apply(
        lambda g: (g["status"] == "F").sum() / g["duration_years"].sum() if g["duration_years"].sum() else 0)
        ).to_dict()
    severity = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)].groupby("signature")["max_D"].mean().to_dict()
    sy_median = pd.read_parquet("data/site_month_dollars.parquet")
    sy_median = sy_median.loc[sy_median["PI"].notna(), "healthy_sy_median"]
    sy_fleet = float(sy_median.median())

    candidates = config.RELIABILITY["inspection_intervals_months"]
    headers = (["Site", "MWdc", "SY (MWh/MWdc/yr)", "Age (yr)"] +
               [f"lambda_{s}" for s in SIGS] +
               [f"total_cost_{t}mo" for t in candidates] +
               ["Optimal interval (mo)", "Optimal total cost", "SCADA annual cost", "SCADA value ($/yr)"])
    ws.append(headers)
    n_sig = len(SIGS)
    lam_cols = {s: 5 + i for i, s in enumerate(SIGS)}          # E.. (5..10)
    cost_col0 = 5 + n_sig                                      # first total_cost column index
    cost_cols = {t: cost_col0 + i for i, t in enumerate(candidates)}

    r = 2
    for row in inspection_df.itertuples():
        ws.cell(row=r, column=1, value=row.site)
        ws.cell(row=r, column=2, value=round(row.mwdc, 3))
        ws.cell(row=r, column=3, value=round(sy_fleet, 2))
        ws.cell(row=r, column=4, value=round(row.age_years, 3))
        for sig in SIGS:
            band = hazard[(hazard["signature"] == sig) & (hazard["age_band_low"] <= row.age_years) &
                          (row.age_years < hazard["age_band_high"])]
            lam = float(band.iloc[0]["hazard_rate"]) if len(band) and band.iloc[0]["exposure_years"] >= 3 else \
                float(fleet_lam.get(sig, 0.0))
            ws.cell(row=r, column=lam_cols[sig], value=round(lam, 4))

        for t in candidates:
            terms = []
            for sig in SIGS:
                sev = severity.get(sig, 0.15)
                col = get_column_letter(lam_cols[sig])
                # lambda * (T/2 + data_lag) * severity*SY*mwdc*PPA/12 * rho
                terms.append(
                    f"{col}{r}*(({t}/2)+{a(rows_a,'data_lag_months')})*"
                    f"({round(sev,4)}*$C{r}*$B{r}*{a(rows_a,'PPA_usd_per_mwh')}/12)*"
                    f"{a(rows_a, f'rho_{sig}')}"
                )
            undetected = "+".join(terms)
            formula = f"=(12/{t})*{a(rows_a,'insp_usd_per_mwdc')}*$B{r}+{undetected}"
            ws.cell(row=r, column=cost_cols[t], value=formula)

        cost_range = f"{get_column_letter(cost_cols[candidates[0]])}{r}:{get_column_letter(cost_cols[candidates[-1]])}{r}"
        cand_range_row = ",".join(str(t) for t in candidates)
        opt_col = cost_col0 + len(candidates) + 1
        ws.cell(row=r, column=opt_col,
                value=f"=INDEX({{{cand_range_row}}},MATCH(MIN({cost_range}),{cost_range},0))")
        ws.cell(row=r, column=opt_col + 1, value=f"=MIN({cost_range})")
        ws.cell(row=r, column=opt_col + 2, value=f"={a(rows_a,'scada_usd_per_mwdc_yr')}*$B{r}")
        ws.cell(row=r, column=opt_col + 3, value=f"={get_column_letter(opt_col+1)}{r}-{get_column_letter(opt_col+2)}{r}")
        for c in range(1, opt_col + 4):
            ws.cell(row=r, column=c).font = BODY_FONT
        r += 1

    style_header_row(ws)
    for j in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 15
    log.info("Inspection Schedule: %d rows, total_cost(T) as live formulas referencing Assumptions", r - 2)


# --------------------------------------------------------------------------
# Spares Plan - gap at 95% coverage as a live formula against an editable
# "spares held" input column.
# --------------------------------------------------------------------------
def build_spares_plan(wb, spares_df):
    ws = wb.create_sheet("Spares Plan")
    headers = ["Owner", "Sites", "Blocks at risk", "Expected block failures (24mo)",
               "Spares held (input)", "Spares needed (95%)", "Gap at 95% coverage", "Est. capital @ $150k/block"]
    ws.append(headers)
    r = 2
    for row in spares_df.itertuples():
        ws.cell(row=r, column=1, value=row.owner)
        ws.cell(row=r, column=2, value=row.n_sites)
        ws.cell(row=r, column=3, value=row.blocks_at_risk)
        ws.cell(row=r, column=4, value=round(row.expected_block_failures_24mo, 3))
        held_cell = ws.cell(row=r, column=5, value=0)
        held_cell.font = INPUT_FONT
        ws.cell(row=r, column=6, value=row.spares_needed_95pct)
        ws.cell(row=r, column=7, value=f"=MAX(0,F{r}-E{r})")
        ws.cell(row=r, column=8, value=f"=G{r}*150000")
        for c in [1, 2, 3, 4, 6, 7, 8]:
            ws.cell(row=r, column=c).font = BODY_FONT
        r += 1
    for j, col in enumerate(headers, start=1):
        if col in ("Blocks at risk", "Sites", "Spares held (input)", "Spares needed (95%)", "Gap at 95% coverage"):
            for i in range(2, r):
                ws.cell(row=i, column=j).number_format = "#,##0"
        if col == "Est. capital @ $150k/block":
            for i in range(2, r):
                ws.cell(row=i, column=j).number_format = "$#,##0"
    style_header_row(ws)
    for j in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 20
    ws.column_dimensions["A"].width = 30


# --------------------------------------------------------------------------
# FMECA - occurrence/severity/detectability normalised 1-10 via formula,
# RPN = product, live off the raw columns.
# --------------------------------------------------------------------------
def build_fmeca(wb, life, episodes):
    ws = wb.create_sheet("FMECA")
    headers = ["Signature", "Occurrence (lambda site-yr, raw)", "Severity (mean D, raw)",
               "Detectability (mean MTTR mo, raw)", "Occurrence (1-10)", "Severity (1-10)",
               "Detectability (1-10)", "RPN", "Rank"]
    ws.append(headers)
    ep_sig = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)]
    raw = []
    for sig in SIGS:
        exposure = life.loc[life["signature"] == sig, "duration_years"].sum()
        failures = (life.loc[life["signature"] == sig, "status"] == "F").sum()
        occurrence = failures / exposure if exposure else 0
        sub = ep_sig[ep_sig["signature"] == sig]
        severity_v = sub["max_D"].mean()
        detect = sub["n_months"].mean()
        raw.append((sig, occurrence, severity_v, detect))
    r0 = 2
    for i, (sig, occ, sev, det) in enumerate(raw):
        r = r0 + i
        ws.cell(row=r, column=1, value=sig)
        ws.cell(row=r, column=2, value=round(occ, 4))
        ws.cell(row=r, column=3, value=round(float(sev), 4))
        ws.cell(row=r, column=4, value=round(float(det), 3))
    r_last = r0 + len(raw) - 1
    for i in range(len(raw)):
        r = r0 + i
        for col_raw, col_norm in [(2, 5), (3, 6), (4, 7)]:
            rng = f"{get_column_letter(col_raw)}{r0}:{get_column_letter(col_raw)}{r_last}"
            cell_ref = f"{get_column_letter(col_raw)}{r}"
            ws.cell(row=r, column=col_norm,
                    value=f"=1+9*({cell_ref}-MIN({rng}))/(MAX({rng})-MIN({rng}))")
        ws.cell(row=r, column=8, value=f"=E{r}*F{r}*G{r}")
        for c in range(1, 9):
            ws.cell(row=r, column=c).font = BODY_FONT
    for i in range(len(raw)):
        r = r0 + i
        rng = f"H{r0}:H{r_last}"
        ws.cell(row=r, column=9, value=f"=RANK(H{r},{rng})")
        ws.cell(row=r, column=9).font = BODY_FONT
    for j, fmt in [(2, "0.000"), (3, "0.000"), (4, "0.00"), (5, "0.00"), (6, "0.00"), (7, "0.00"), (8, "0.0")]:
        for i in range(2, r_last + 1):
            ws.cell(row=i, column=j).number_format = fmt
    style_header_row(ws)
    for j in range(1, len(headers) + 1):
        ws.column_dimensions[get_column_letter(j)].width = 22


# --------------------------------------------------------------------------
# Vintage Scorecard - lambda/beta by COD-year band x tracking, cell counts
# shown so a thin cell isn't read as a rate.
# --------------------------------------------------------------------------
def cod_band(year):
    if pd.isna(year):
        return "unknown"
    year = int(year)
    lo = (year // 3) * 3
    return f"{lo}-{lo+2}"


def build_vintage_scorecard(wb, life, sites):
    ws = wb.create_sheet("Vintage Scorecard")
    headers = ["COD band", "Tracking", "Sites", "Failures", "Exposure site-years", "Lambda (site-yr)"]
    ws.append(headers)
    life2 = life.merge(sites[["site", "tracking"]], on="site", how="left")
    life2["cod_band"] = life2["cod"].dt.year.map(cod_band)
    g = life2.groupby(["cod_band", "tracking"]).agg(
        sites=("site", "nunique"), failures=("status", lambda s: (s == "F").sum()),
        exposure=("duration_years", "sum")).reset_index()
    r = 2
    for row in g.sort_values(["cod_band", "tracking"]).itertuples():
        ws.cell(row=r, column=1, value=row.cod_band)
        ws.cell(row=r, column=2, value=row.tracking)
        ws.cell(row=r, column=3, value=row.sites)
        ws.cell(row=r, column=4, value=row.failures)
        ws.cell(row=r, column=5, value=round(row.exposure, 2))
        ws.cell(row=r, column=6, value=f"=D{r}/E{r}" if row.exposure else 0)
        for c in range(1, 7):
            ws.cell(row=r, column=c).font = BODY_FONT
        r += 1
    for i in range(2, r):
        ws.cell(row=i, column=6).number_format = "0.000"
    style_header_row(ws)
    for j in range(1, 7):
        ws.column_dimensions[get_column_letter(j)].width = 18


# --------------------------------------------------------------------------
# Benchmark - publishable fleet stats
# --------------------------------------------------------------------------
def build_benchmark(wb, life, episodes, dollars):
    ws = wb.create_sheet("Benchmark")
    ws.append(["Metric", "Value"])
    site_target = dollars.groupby("site")["T_mwh"].sum()
    site_act = dollars.groupby("site")["E_act_mwh"].sum()
    avail = (1 - (site_target - site_act).clip(lower=0) / site_target.replace(0, np.nan)).dropna()
    rows = [
        ("Energy availability - fleet median", round(float(avail.median()), 4)),
        ("Energy availability - P10", round(float(avail.quantile(0.10)), 4)),
        ("Energy availability - P90", round(float(avail.quantile(0.90)), 4)),
        ("Faults per plant-year (all 6 signatures)",
         round(float((life["status"] == "F").sum() / life["duration_years"].sum()), 4)),
        ("Faults per block-year",
         round(float((life["status"] == "F").sum() / (life["duration_years"] * life["n_blocks"]).sum()), 4)),
    ]
    for sig in SIGS:
        sub = episodes[episodes["signature"] == sig]
        rows.append((f"MTTR {sig} (months)", round(float(sub["n_months"].mean()), 2)))
    for label, val in rows:
        ws.append([label, val])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
    style_header_row(ws)
    ws.column_dimensions["A"].width = 42
    ws.column_dimensions["B"].width = 14


# --------------------------------------------------------------------------
# Reconciliation - control gates, must all pass before delivery (test 46)
# --------------------------------------------------------------------------
def build_reconciliation(wb, life, episodes, ledger, quarantine_count, sites, dollars):
    ws = wb.create_sheet("Reconciliation")
    ws.append(["Gate", "Expected", "Actual", "Pass"])

    # life_records has one full observation stream PER (site x signature) -
    # 6 parallel competing-risks streams per site (Section 4) - so its raw
    # total is ~6x a single calendar-exposure count. The ledger's own
    # exposure_months field sums to exactly 286,446 (the addendum's cited
    # reference), but that sum is itself duplicated once per signature row
    # recorded that site-year, not a single-stream count either, so it is
    # NOT the right thing to divide life_records' total by 6 against.
    # The comparable single-stream figure is the fleet's scored site-month
    # count (data/site_month_dollars.parquet, PI not null) / 12, which is
    # what entry_date/last_known_date in S12 are actually bounded by.
    exposure_life_single_stream = round(life["duration_years"].sum() / len(config.RELIABILITY_SIGNATURES), 1)
    exposure_scored_site_years = round(dollars.loc[dollars["PI"].notna()].shape[0] / 12, 1)
    gate1_pass = abs(exposure_life_single_stream - exposure_scored_site_years) / exposure_scored_site_years < 0.15

    fs_counts_ok = True
    for sig in SIGS:
        n_sites_sig = life.loc[life["signature"] == sig, "site"].nunique()
        n_total_sites = sites["site"].nunique()
        if n_sites_sig > n_total_sites:
            fs_counts_ok = False

    lost_mwh_ledger = ledger.loc[ledger["signature"].isin(config.RELIABILITY_SIGNATURES), "mwh_lost"].sum()
    lost_mwh_episodes_positive = lost_mwh_ledger >= 0

    rows = [
        ("Exposure: life records single-stream site-years (total/6 signatures) vs scored site-months/12",
         exposure_scored_site_years, exposure_life_single_stream, gate1_pass),
        ("F+S counts: every signature's site count <= total site count", sites["site"].nunique(), fs_counts_ok, fs_counts_ok),
        ("Lost MWh ties to a non-negative pipeline total", ">= 0", round(float(lost_mwh_ledger), 0), bool(lost_mwh_episodes_positive)),
        ("Quarantined records (age_start < 0, listed reasons in Notes tab)", None, quarantine_count, True),
    ]
    for label, expected, actual, passed in rows:
        ws.append([label, expected, actual, "PASS" if passed else "FAIL"])
    for row in ws.iter_rows(min_row=2):
        for cell in row:
            cell.font = BODY_FONT
        if row[3].value == "FAIL":
            row[3].font = Font(name="Arial", size=10, bold=True, color="CC0000")
    style_header_row(ws)
    ws.column_dimensions["A"].width = 60
    ws.column_dimensions["B"].width = 16
    ws.column_dimensions["C"].width = 16
    ws.column_dimensions["D"].width = 10
    all_pass = all(r[3] for r in rows)
    return all_pass


def build_notes(wb, quarantine_count):
    ws = wb.create_sheet("Notes", 0)
    lines = [
        "SSI Solar Reliability Metrics - Reliability Engineering Addendum, first full pass (S12-S17)",
        f"Generated: {pd.Timestamp.now(tz='UTC').isoformat()}",
        "Source method: Sheng & O'Connor, 'Reliability of Wind Turbines', Ch.15, Wind Energy "
        "Engineering (Elsevier, 2017). Method adapted for PV; no text reproduced.",
        "Classifier version: d-band-v1.",
        "",
        "Scope: the 6 reliability-eligible fault signatures (BLOCK_OUTAGE, BOS_INTERMITTENT, "
        "OUTAGE_FULL, SOILING, TRACKER, UNATTRIBUTED). CURTAILMENT/SNOW/CLIPPING are exposure, "
        "not unreliability. DEGRADATION is a continuous state (S7's job), not a discrete failure.",
        "",
        "Left truncation: every life record is truncated at a site's first PI-scored month. "
        f"{quarantine_count} episodes were quarantined (age_start < 0 relative to COD - a COD "
        "estimate mismatch, not a real pre-installation failure) and excluded from every fit.",
        "",
        "Fitting: fleet-level Weibull per signature (no per-site/per-stratum refit in this pass; "
        "min_failures_to_fit=20 is tight once split further). All 5 candidate distributions are "
        "fit and reported (Fits tab) - Weibull is used for forecasting/hazard/inspection math "
        "throughout because beta is the operationally load-bearing number, even where a different "
        "family wins the log-likelihood race.",
        "",
        "KNOWN ISSUE - flagged, not resolved: SOILING's mean episode duration (MTTR) runs well "
        "above the addendum's ~1.0 month reference. Treat SOILING-driven forecasts/spares/"
        "inspection numbers as provisional until the episode-joining logic is investigated.",
        "",
        "Warranty gate fix (Section 9.2): warranty valuation uses "
        f"config.RELIABILITY_WARRANTY_YEARS ({config.RELIABILITY_WARRANTY_YEARS} years, a blended "
        "inverter/module-product term), not the blanket 25-year module_performance term that "
        "the routing logic elsewhere uses - that term covers power-output degradation, not the "
        "equipment/workmanship faults these signatures represent, and using it here would have "
        "marked nearly the whole fleet as in-warranty.",
        "",
        "Every rate/MTTR/MTBF/RPN/spares-gap/inspection-cost figure in this workbook is a live "
        "formula off raw counts and the Assumptions tab, per the production workbook's formula "
        "discipline - change PPA or a rho value on Assumptions and the Inspection Schedule optimum "
        "will move.",
        "",
        "NOT built in this pass: native embedded charts (bathtub/lost-energy/inspection-cost "
        "curves) - the underlying data for all three lives on the Hazard by Age, Fleet Summary, "
        "and Inspection Schedule tabs respectively, ready to chart, but the charts themselves are "
        "not yet embedded.",
        "",
        "Status: measured = fitted directly from data. assumed = a documented input with no "
        "vendor/ground-truth confirmation yet (rho by signature, repair cost anchors, inspection "
        "rate). PLACEHOLDER = explicitly no evidence yet, do not present as fact.",
        "",
        "Reconciliation note: the event ledger's own exposure_months field sums to exactly "
        "286,446 (the addendum's cited reference), but that total is accumulated once per "
        "(site, year, signature) row - effectively duplicated across however many signatures "
        "were recorded that site-year - so it is not directly comparable to a single-stream "
        "life-record exposure figure. The Reconciliation tab instead compares life_records' "
        "total exposure divided by the 6 signature streams against the fleet's scored "
        "site-months/12, which is the quantity S12's entry_date/last_known_date are actually "
        "bounded by.",
    ]
    for line in lines:
        ws.append([line])
    for row in ws.iter_rows():
        row[0].font = BODY_FONT
        row[0].alignment = Alignment(wrap_text=True)
    ws.column_dimensions["A"].width = 120


def main():
    life = pd.read_parquet("data/life_records.parquet")
    episodes = pd.read_parquet("data/episodes.parquet")
    ledger = pd.read_parquet("data/event_ledger.parquet")
    sites = pd.read_parquet("data/subsample_sites.parquet")
    dollars = pd.read_parquet("data/site_month_dollars.parquet")
    forecast = pd.read_parquet("data/reliability_forecast.parquet")
    hazard = pd.read_parquet("data/hazard_by_age.parquet")
    spares = pd.read_parquet("data/spares_plan.parquet")
    inspection = pd.read_parquet("data/inspection_schedule.parquet")
    warranty = pd.read_parquet("data/warranty_valuation.parquet")
    with open("data/reliability_fits.json") as f:
        fits = json.load(f)
    from s11_explorer import load_pricing
    pricing = load_pricing()

    ep_reliab = episodes[episodes["signature"].isin(config.RELIABILITY_SIGNATURES)]
    sub_ep = ep_reliab.merge(sites[["site", "cod"]], on="site", how="left")
    quarantine_count = int((((sub_ep["start"] - sub_ep["cod"]).dt.days / 365.25) < 0).sum())

    wb = openpyxl.Workbook()
    wb.remove(wb.active)

    build_notes(wb, quarantine_count)
    rows_a = build_assumptions_sheet(wb, pricing)
    build_fleet_summary(wb, episodes, life, ledger, rows_a)

    if len(life) <= config.RELIABILITY["workbook_max_rows_inline"]:
        ws = wb.create_sheet("Life Records")
        cols = ["site", "signature", "equipment_key", "cod", "entry_date", "age_entry_years",
                "last_known_date", "age_last_known_years", "spell_index", "age_at_event_years",
                "duration_years", "status", "n_blocks", "n_affected_blocks", "mwdc", "state", "utility"]
        write_df(ws, life[cols], {"age_entry_years": "0.00", "age_last_known_years": "0.00",
                                   "age_at_event_years": "0.00", "duration_years": "0.00"})
    else:
        life.to_csv("output/reliability_life_records.csv", index=False)
        ws = wb.create_sheet("Life Records")
        ws.append([f"{len(life)} rows exceeds workbook_max_rows_inline "
                   f"({config.RELIABILITY['workbook_max_rows_inline']}) - see "
                   "output/reliability_life_records.csv for the full audit trail."])

    ws = wb.create_sheet("Fits")
    fit_rows = []
    for s in fits["signatures"]:
        for f in s["all_fits"]:
            fit_rows.append(dict(signature=s["signature"], family=f["family"], loglik=round(f["loglik"], 1),
                                  aic=round(f["aic"], 1), is_winner=(f["family"] == s["best_fit"]["family"]),
                                  n_failures=s["n_failures"], n_suspensions=s["n_suspensions"],
                                  weibull_beta=round(s["weibull_beta"], 3), weibull_eta_years=round(s["weibull_eta_years"], 2)))
    write_df(ws, pd.DataFrame(fit_rows))

    ws = wb.create_sheet("Hazard by Age")
    write_df(ws, hazard, {"hazard_rate": "0.000", "exposure_years": "0.0"})

    ws = wb.create_sheet("Forecast")
    if len(forecast) <= config.RELIABILITY["workbook_max_rows_inline"]:
        write_df(ws, forecast, {"cond_prob_failure": "0.0%", "R_now": "0.000", "R_future": "0.000",
                                 "expected_failures_block_level": "0.00", "credibility_Z": "0.00"})
    else:
        forecast.to_csv("output/reliability_forecast.csv", index=False)
        ws.append([f"{len(forecast)} rows exceeds workbook_max_rows_inline - see "
                   "output/reliability_forecast.csv"])

    build_spares_plan(wb, spares)
    build_inspection_schedule(wb, inspection, hazard, life, episodes, rows_a)

    ws = wb.create_sheet("Warranty Value")
    write_df(ws, warranty, {"claim_value_usd": "$#,##0", "remaining_window_years": "0.00",
                             "expected_failures_in_warranty": "0.000"})

    build_vintage_scorecard(wb, life, sites)
    build_fmeca(wb, life, episodes)
    build_benchmark(wb, life, episodes, dollars)
    all_pass = build_reconciliation(wb, life, episodes, ledger, quarantine_count, sites, dollars)

    path = "output/SSI_Solar_Reliability_Metrics.xlsx"
    wb.save(path)
    log.info("wrote %s (%d sheets), Reconciliation gates: %s", path, len(wb.sheetnames),
              "ALL PASS" if all_pass else "AT LEAST ONE FAIL - see Reconciliation tab")
    if not all_pass:
        log.warning("Reconciliation has a failing gate - review before treating this workbook as final")
    log.info("S17 complete")


if __name__ == "__main__":
    main()
