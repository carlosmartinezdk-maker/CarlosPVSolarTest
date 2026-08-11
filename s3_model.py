"""
S3 - Hourly pvlib model, summed to month. THE MODEL RUNS HOURLY, THE METRIC
IS MONTHLY - averaging irradiance first would systematically overstate
output (Jensen's inequality on the clipping min() and the temperature
nonlinearity), most for high DC:AC plants.
"""
import logging
import os

import numpy as np
import pandas as pd
import pvlib
from pvlib import irradiance, location, temperature, tracking

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s S3 %(message)s")
log = logging.getLogger("s3")

DEFAULT_GCR = 0.35  # ground coverage ratio for single-axis backtracking; not
                     # provided by either input file, documented default


def grid_cell(lat: float, lon: float) -> tuple[float, float]:
    g = config.NSRDB_GRID_DEG
    return (round(lat / g) * g, round(lon / g) * g)


def _weather_cache_paths(grid_lat: float, grid_lon: float, year: int) -> dict:
    base = os.path.join(config.NSRDB_CACHE_DIR, f"grid_lat={grid_lat}",
                        f"grid_lon={grid_lon}", f"year={year}")
    return {"A": os.path.join(base, "weather_A.parquet"),
            "B": os.path.join(base, "weather_B.parquet")}


def load_weather(grid_lat: float, grid_lon: float, year: int) -> tuple[pd.DataFrame, str]:
    """S2's real Track A pull is preferred; weather_B.parquet is the
    dev/test-only clear-sky stopgap (dev_clearsky_cache.py), used only when
    Track A is absent. Never silently invents data - raises if neither
    exists (test 31: name the missing partition, don't guess)."""
    paths = _weather_cache_paths(grid_lat, grid_lon, year)
    if os.path.exists(paths["A"]):
        return pd.read_parquet(paths["A"]), "A"
    if os.path.exists(paths["B"]):
        return pd.read_parquet(paths["B"]), "B_clearsky_stopgap"
    raise FileNotFoundError(
        f"no cached weather for grid cell (grid_lat={grid_lat}, grid_lon={grid_lon}, "
        f"year={year}) - neither weather_A.parquet (S2 real pull) nor weather_B.parquet "
        f"(dev_clearsky_cache.py stopgap) exists. Run one of them for this cell-year "
        f"before S3."
    )


def check_cache_complete(sites: "pd.DataFrame", years: list[int]) -> None:
    """Test 31: refuse to start and name every missing partition, rather
    than silently modelling whatever subset happens to be cached."""
    missing = []
    seen_cells = set()
    for _, row in sites.iterrows():
        cell = grid_cell(row["lat"], row["lon"])
        for year in years:
            key = (cell, year)
            if key in seen_cells:
                continue
            seen_cells.add(key)
            paths = _weather_cache_paths(cell[0], cell[1], year)
            if not (os.path.exists(paths["A"]) or os.path.exists(paths["B"])):
                missing.append((cell[0], cell[1], year))
    if missing:
        preview = "\n  ".join(f"grid_lat={m[0]}, grid_lon={m[1]}, year={m[2]}" for m in missing[:20])
        more = f"\n  ... and {len(missing) - 20} more" if len(missing) > 20 else ""
        raise RuntimeError(
            f"S3 cache incomplete: {len(missing)} of {len(seen_cells)} required cell-years "
            f"are missing from {config.NSRDB_CACHE_DIR}. Run s2_nsrdb.py (real pull) or "
            f"dev_clearsky_cache.py (dev stopgap) for these first:\n  {preview}{more}"
        )
    log.info("cache complete: all %d required cell-years present", len(seen_cells))


def poa_irradiance(weather: pd.DataFrame, loc: location.Location, tracking_type: str,
                    tilt: float, azimuth: float, dcac: float) -> tuple[pd.Series, dict]:
    times = weather.index
    solpos = loc.get_solarposition(times)
    dni_extra = irradiance.get_extra_radiation(times)
    albedo = weather["surface_albedo"].fillna(0.2).clip(0.05, 0.9)

    flags = {}
    if tracking_type == "Single-axis":
        axis_azimuth = azimuth if pd.notna(azimuth) and 0 < azimuth < 360 else 180.0
        tr = tracking.singleaxis(
            apparent_zenith=solpos["apparent_zenith"], solar_azimuth=solpos["azimuth"],
            axis_tilt=0, axis_azimuth=axis_azimuth, max_angle=60,
            backtrack=True, gcr=DEFAULT_GCR,
        )
        surface_tilt = tr["surface_tilt"].fillna(0)
        surface_azimuth = tr["surface_azimuth"].fillna(axis_azimuth)
    elif tracking_type == "Dual-axis":
        surface_tilt = solpos["apparent_zenith"].clip(upper=90)
        surface_azimuth = solpos["azimuth"]
    elif tracking_type == "Fixed tilt":
        t = tilt if pd.notna(tilt) and 0 <= tilt <= 90 else min(max(abs(loc.latitude), 10), 40)
        az = azimuth if pd.notna(azimuth) and 0 <= azimuth < 360 else 180.0
        surface_tilt = pd.Series(t, index=times)
        surface_azimuth = pd.Series(az, index=times)
    else:
        # Unknown / Mixed - documented default: fixed tilt at latitude, south
        # (north-hemisphere fleet). Flagged by the caller via tracking_type.
        surface_tilt = pd.Series(min(max(abs(loc.latitude), 10), 40), index=times)
        surface_azimuth = pd.Series(180.0, index=times)
        flags["tracking_default_applied"] = True

    poa = irradiance.get_total_irradiance(
        surface_tilt=surface_tilt, surface_azimuth=surface_azimuth,
        solar_zenith=solpos["apparent_zenith"], solar_azimuth=solpos["azimuth"],
        dni=weather["dni"].clip(lower=0), ghi=weather["ghi"].clip(lower=0),
        dhi=weather["dhi"].clip(lower=0), dni_extra=dni_extra, albedo=albedo,
        model="haydavies",
    )
    return poa["poa_global"].fillna(0), flags


def time_varying_pdc(generators: pd.DataFrame, plant_id: float, fallback_mwdc: float,
                      cod_fallback: pd.Timestamp, month_starts: pd.DatetimeIndex) -> pd.Series:
    """P_dc_i(m) per Section 6 / S4a: sum of dc_net_capacity_mw over
    generators whose COD <= m. Falls back to constant site_master.mwdc when
    no generator rows exist for this plant (either not phased, or the asset
    file lacks a match)."""
    gens = generators[generators["plant_id"] == plant_id]
    if len(gens) == 0:
        return pd.Series(fallback_mwdc, index=month_starts)

    out = []
    for m in month_starts:
        cod = gens["generator_cod"].fillna(cod_fallback)
        active = gens.loc[cod <= m, "dc_net_capacity_mw"]
        out.append(active.sum() if len(active) else fallback_mwdc)
    return pd.Series(out, index=month_starts)


def run_site_year(site_row: pd.Series, generators: pd.DataFrame, year: int,
                   month_starts_all: pd.DatetimeIndex) -> pd.DataFrame:
    lat, lon = site_row["lat"], site_row["lon"]
    glat, glon = grid_cell(lat, lon)
    weather, weather_track = load_weather(glat, glon, year)
    loc = location.Location(lat, lon, tz=weather.index.tz)

    tracking_type = site_row["tracking"] if site_row["tracking"] in (
        "Single-axis", "Fixed tilt", "Dual-axis") else "Unknown"
    poa, flags = poa_irradiance(weather, loc, tracking_type,
                                 site_row.get("tilt", np.nan), site_row.get("azimuth", np.nan),
                                 site_row.get("dcac", 1.3))

    u0, u1 = config.FAIMAN_U0, config.FAIMAN_U1
    t_cell = temperature.faiman(poa, weather["air_temperature"], weather["wind_speed"], u0, u1)

    gamma = config.GAMMA_TEMP_COEFF["cdte" if site_row["tech_class"] == "cdte" else "crystalline_silicon"]
    d_rate = config.DEGRADATION_RATE_ANNUAL["cdte" if site_row["tech_class"] == "cdte" else "crystalline_silicon"]

    month_starts_year = month_starts_all[month_starts_all.year == year]
    cod = site_row["cod"] if pd.notna(site_row["cod"]) else month_starts_year.min()
    pdc_by_month = time_varying_pdc(generators, site_row["plant_id"], site_row["mwdc"],
                                     cod, month_starts_year)

    months_index = weather.index.to_period("M").start_time
    pdc_hourly = months_index.map(lambda m: pdc_by_month.get(m, site_row["mwdc"]))
    pdc_hourly = pd.Series(pdc_hourly, index=weather.index).astype(float)

    age_years = np.clip((weather.index.tz_localize(None) - pd.Timestamp(cod)).days / 365.25, 0, None)

    p_dc = (pdc_hourly * (poa / 1000.0) * (1 + gamma * (t_cell - 25))
            * config.STATIC_LOSS_STACK * (1 - d_rate) ** age_years)
    p_dc = p_dc.clip(lower=0)
    p_ac_i = site_row["mwac"]
    p_ac = (p_dc * config.INVERTER_EFFICIENCY).clip(upper=p_ac_i)

    # IEC 61724-1 PR_T denominator integrand: (poa/1000)*(1+gamma*(t_cell-25)),
    # summed over the month's hours - the temperature correction sits INSIDE
    # the irradiance-weighted sum, never applied to a monthly average.
    pr_t_integrand = (poa / 1000.0) * (1 + gamma * (t_cell - 25))

    df = pd.DataFrame({
        "p_ac_mw": p_ac, "poa_wm2": poa, "t_cell_c": t_cell,
        "pr_t_integrand": pr_t_integrand, "p_dc_mw": pdc_hourly,
        "clipped": p_dc * config.INVERTER_EFFICIENCY > p_ac_i,
        "month_start": months_index,
    })
    monthly = df.groupby("month_start").agg(
        E_exp_mwh=("p_ac_mw", "sum"),
        poa_kwh_m2=("poa_wm2", lambda s: s.sum() / 1000.0),
        mean_cell_temp_c=("t_cell_c", "mean"),
        clipped_hours=("clipped", "sum"),
        pr_t_denom=("pr_t_integrand", "sum"),
        p_dc_mw=("p_dc_mw", "first"),
    ).reset_index()
    monthly["site"] = site_row["site"]
    monthly["year"] = year
    monthly["weather_track"] = weather_track
    monthly["tracking_default_applied"] = flags.get("tracking_default_applied", False)
    return monthly


def run_site_year_no_irradiance(site_row: pd.Series, generators: pd.DataFrame, year: int,
                                 month_starts_all: pd.DatetimeIndex) -> pd.DataFrame:
    """Section 0.7 / test 27: NSRDB has no 2026 data, so E_exp (and
    therefore PI, PR_T) are null for every 2026 month - never substitute a
    clear-sky estimate. SY needs no irradiance at all (E_act / P_dc), so
    P_dc_i(m) is still computed here and PRI stays scoreable."""
    month_starts_year = month_starts_all[month_starts_all.year == year]
    cod = site_row["cod"] if pd.notna(site_row["cod"]) else month_starts_year.min()
    pdc_by_month = time_varying_pdc(generators, site_row["plant_id"], site_row["mwdc"],
                                     cod, month_starts_year)
    monthly = pd.DataFrame({
        "month_start": month_starts_year,
        "E_exp_mwh": np.nan, "poa_kwh_m2": np.nan, "mean_cell_temp_c": np.nan,
        "clipped_hours": np.nan, "pr_t_denom": np.nan,
        "p_dc_mw": [pdc_by_month.get(m, site_row["mwdc"]) for m in month_starts_year],
    })
    monthly["site"] = site_row["site"]
    monthly["year"] = year
    monthly["weather_track"] = "no_irradiance_2026"
    monthly["tracking_default_applied"] = False
    return monthly


def main(sites_path="data/subsample_sites.parquet"):
    sites = pd.read_parquet(sites_path)
    generators = pd.read_parquet("data/generators.parquet")
    month_starts_all = pd.date_range("2019-01-01", "2026-05-01", freq="MS")

    all_scored_years = config.NSRDB_YEARS + [2026]  # 2026 scored PRI-only, no irradiance (Section 0.7)

    # Test 31: refuse to start rather than silently model a partial fleet.
    check_cache_complete(sites, config.NSRDB_YEARS)

    results = []
    n = len(sites)
    for i, (_, site_row) in enumerate(sites.iterrows()):
        for year in all_scored_years:
            if year == 2026 and config.YEAR_2026_HAS_NO_IRRADIANCE:
                results.append(run_site_year_no_irradiance(site_row, generators, year, month_starts_all))
                continue
            try:
                monthly = run_site_year(site_row, generators, year, month_starts_all)
                results.append(monthly)
            except FileNotFoundError as e:
                log.warning("skip %s %d: %s", site_row["site"], year, e)
        if (i + 1) % 10 == 0 or i == n - 1:
            log.info("S3 progress: %d/%d sites", i + 1, n)

    out = pd.concat(results, ignore_index=True)
    out.to_parquet("data/expected_generation.parquet", index=False)
    log.info("S3 complete: %d site-months of expected generation (%s)",
              len(out), out["weather_track"].value_counts().to_dict())

    write_pull_summary(out, sites)
    return out


def write_pull_summary(monthly: pd.DataFrame, sites: pd.DataFrame) -> None:
    """One row per (grid_lat, grid_lon, year) cell-year S3 actually loaded
    weather for, tagged with which track ('A' real NSRDB or
    'B_clearsky_stopgap') it came from. This is the source of truth S10/S11
    read to report the run's real-vs-stopgap data honestly instead of
    assuming Track B (test 28 in test_s2_contract.py checks it's complete:
    exactly one row per cell x year, no silent partial cache)."""
    cell_years = monthly[monthly["weather_track"] != "no_irradiance_2026"][
        ["site", "year", "weather_track"]].copy()
    latlon = sites.set_index("site")[["lat", "lon"]]
    cell_years["lat"] = cell_years["site"].map(latlon["lat"])
    cell_years["lon"] = cell_years["site"].map(latlon["lon"])
    cell_years["grid_lat"], cell_years["grid_lon"] = zip(
        *cell_years.apply(lambda r: grid_cell(r["lat"], r["lon"]), axis=1))
    summary = (cell_years.groupby(["grid_lat", "grid_lon", "year"])["weather_track"]
               .first().reset_index().rename(columns={"weather_track": "track"}))
    summary.to_parquet("data/nsrdb_pull_summary.parquet", index=False)
    log.info("S3 wrote data/nsrdb_pull_summary.parquet: %d cell-years (%s)",
              len(summary), summary["track"].value_counts().to_dict())


if __name__ == "__main__":
    main()
