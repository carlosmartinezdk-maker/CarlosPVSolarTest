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

    # Phased-build sites (generators > 1) get time-varying P_dc(m) from
    # solar_assets_data.csv in S4a; flagged here for downstream tagging.
    df["is_phased_build"] = df["generators"].fillna(1) > 1
    n_phased = df["is_phased_build"].sum()
    log.info("%d sites flagged generators>1 (phased build) - time-varying "
              "P_dc(m) built from solar_assets_data.csv in S4a.", n_phased)

    log.info("site_master: %d sites, %d with lat/lon+op_year, %d flagged phased-unadjusted",
              len(df), has_cod.sum(), n_phased)
    return df


def load_generators() -> pd.DataFrame:
    """Generator-grain table (solar_assets_data.csv), used by S4a for
    time-varying DC capacity on phased builds. Join key is plant_id."""
    path = os.path.join(RAW_DIR, "solar_assets_data.csv")
    if not os.path.exists(path):
        log.warning("solar_assets_data.csv not found - falling back to empty "
                    "generator table (constant capacity everywhere).")
        cols = ["plant_id", "generator_id", "nameplate_capacity_mw",
                "dc_net_capacity_mw", "operating_year", "operating_month",
                "tilt_angle", "azimuth_angle", "tracking_type",
                "crystalline_silicon", "thin_film_cdte", "latitude", "longitude"]
        return pd.DataFrame(columns=cols)

    df = pd.read_csv(path)
    has_cod = df["operating_year"].notna() & df["operating_month"].notna()
    df["generator_cod"] = pd.NaT
    df.loc[has_cod, "generator_cod"] = pd.to_datetime(
        dict(year=df.loc[has_cod, "operating_year"].astype(int),
             month=df.loc[has_cod, "operating_month"].astype(int),
             day=1)
    )
    n_missing_cod = (~has_cod).sum()
    if n_missing_cod:
        log.warning("%d generator rows missing operating_year/month - their "
                    "capacity cannot be phased in at a specific month; "
                    "treated as present from the plant's earliest known COD.",
                    n_missing_cod)

    multi = df.groupby("plant_id").size()
    n_phased_plants = (multi > 1).sum()
    log.info("solar_assets_data: %d generator rows, %d plants, %d phased "
              "(>1 generator)", len(df), df["plant_id"].nunique(), n_phased_plants)
    return df


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
        assert_workbook_p_equals_z(xlsx, sample_years=["2019", "2022", "2023", "2025"])

    log.info("S0 complete: production.parquet (%d rows), sites.parquet (%d rows), "
              "generators.parquet (%d rows)",
              len(production), len(sites), len(generators))


if __name__ == "__main__":
    main()
