"""
S0 - Load and normalise. CSVs -> parquet. COD construction. Null-vs-zero
integrity. No k-notation conversion, no annual rescaling (that belonged to
the v1 200-site quantised dataset and would be wrong here).
"""
import datetime as dt
import logging
import os

import pandas as pd

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S0 %(message)s")
log = logging.getLogger("s0")

RAW_DIR = "data/raw"
OUT_DIR = "data"


def load_production() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(RAW_DIR, "production_long.csv"),
                      dtype={"period": str}, low_memory=False)
    df["month_start"] = pd.to_datetime(df["month_start"])
    df["reported"] = df["reported"].astype(bool)
    df["is_partial_year"] = df["is_partial_year"].astype(bool)

    # Integrity check: null mwh iff reported == False. Never let a
    # not-reported month become a reported zero, or vice versa.
    null_mwh = df["mwh"].isna().sum()
    not_reported = (~df["reported"]).sum()
    assert null_mwh == not_reported, (
        f"null mwh ({null_mwh}) != not-reported count ({not_reported}) - "
        "null/zero integrity violated at load"
    )
    mismatch_a = ((df["reported"]) & (df["mwh"].isna())).sum()
    mismatch_b = ((~df["reported"]) & (df["mwh"].notna())).sum()
    assert mismatch_a == 0 and mismatch_b == 0, "reported/mwh null mismatch"

    log.info("production_long: %d rows, %d reported, %d not-reported (null, not zero)",
              len(df), df["reported"].sum(), (~df["reported"]).sum())
    return df


def load_sites() -> pd.DataFrame:
    df = pd.read_csv(os.path.join(RAW_DIR, "site_master.csv"))

    # COD = date(op_year, op_month, 1). Use the reported month; never assume Jan.
    has_cod = df["op_year"].notna() & df["op_month"].notna()
    df["cod"] = pd.NaT
    df.loc[has_cod, "cod"] = pd.to_datetime(
        dict(year=df.loc[has_cod, "op_year"].astype(int),
             month=df.loc[has_cod, "op_month"].astype(int),
             day=1)
    )

    # Module technology tagging for gamma/degradation lookup (Section 6):
    # c-Si value used for other thin film and Mixed; tag those sites.
    def tech_class(module: str) -> str:
        if not isinstance(module, str):
            return "unknown"
        m = module.lower()
        if "cdte" in m:
            return "cdte"
        return "crystalline_silicon"

    df["tech_class"] = df["module"].apply(tech_class)
    df["tech_class_is_tagged_default"] = ~df["module"].fillna("").str.lower().str.contains("cdte") & \
        df["module"].fillna("").str.lower().str.contains("cigs|thin film|mixed|a-si")

    # solar_assets_data.csv (generator grain) was not provided in this run.
    # KNOWN GAP - flagged per Section 0 discussion with Carlos. Fall back to
    # constant capacity (site_master.mwdc) for all sites; flag phased builds
    # (generators > 1) so downstream trajectory/PRI results carry the flag.
    df["is_phased_build_unadjusted"] = df["generators"].fillna(1) > 1
    n_phased = df["is_phased_build_unadjusted"].sum()
    log.warning(
        "solar_assets_data.csv not provided this run - %d sites flagged "
        "generators>1 will use CONSTANT capacity (site_master.mwdc) instead "
        "of time-varying P_dc(m). Their trajectory/PRI outputs carry "
        "data_quality_flag='phased_build_no_asset_data'.", n_phased
    )

    log.info("site_master: %d sites, %d with lat/lon+op_year, %d flagged phased-unadjusted",
              len(df), has_cod.sum(), n_phased)
    return df


def load_generators() -> pd.DataFrame:
    """Placeholder generator-grain table. solar_assets_data.csv was not
    provided; emit an empty frame with the documented schema so downstream
    code has a stable join target and degrades gracefully."""
    cols = ["plant_id", "generator_id", "nameplate_capacity_mw",
            "dc_net_capacity_mw", "operating_year", "operating_month",
            "tilt_angle", "azimuth_angle", "tracking_type",
            "crystalline_silicon", "thin_film_cdte", "latitude", "longitude"]
    return pd.DataFrame(columns=cols)


def assert_workbook_p_equals_z(xlsx_path: str, sample_years=None) -> None:
    """Test 5 / acceptance test: column P (Total MWh, =SUM(D:O)) must equal
    column Z (Total MWh source, EIA annual total) on every row. Any mismatch
    means a month failed to parse (most likely an em-dash -> 0 bug)."""
    import openpyxl
    wb = openpyxl.load_workbook(xlsx_path, read_only=True, data_only=True)
    years = sample_years or ["2019", "2025"]
    for sheet_name in years:
        if sheet_name not in wb.sheetnames:
            continue
        ws = wb[sheet_name]
        mismatches = 0
        checked = 0
        for row in ws.iter_rows(min_row=2, values_only=True):
            if row[0] is None:
                continue
            p_val, z_val = row[15], row[25]  # P=col16(idx15), Z=col26(idx25)
            if p_val is None or z_val is None:
                continue
            checked += 1
            if abs((p_val or 0) - (z_val or 0)) > 0.5:
                mismatches += 1
        log.info("workbook tab %s: checked %d rows, %d P!=Z mismatches",
                  sheet_name, checked, mismatches)
        assert mismatches == 0, f"{sheet_name}: {mismatches} rows where P != Z"


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    production = load_production()
    sites = load_sites()
    generators = load_generators()

    production.to_parquet(os.path.join(OUT_DIR, "production.parquet"), index=False)
    sites.to_parquet(os.path.join(OUT_DIR, "sites.parquet"), index=False)
    generators.to_parquet(os.path.join(OUT_DIR, "generators.parquet"), index=False)

    xlsx = os.path.join(RAW_DIR, "Solar_Production_and_Asset_Data_FY19_FY26.xlsx")
    if os.path.exists(xlsx):
        assert_workbook_p_equals_z(xlsx, sample_years=["2019", "2023", "2025"])

    log.info("S0 complete: production.parquet (%d rows), sites.parquet (%d rows), "
              "generators.parquet (%d rows, empty placeholder)",
              len(production), len(sites), len(generators))


if __name__ == "__main__":
    main()
