"""
Single source of truth for every constant, threshold and default used by the
PI/PRI/degradation/fault pipeline. Nothing downstream should hardcode a
number that appears here. See BUILD_BRIEF section references in comments.
"""
from dataclasses import dataclass, field

# --------------------------------------------------------------------------
# Track / provenance
# --------------------------------------------------------------------------
TRACK = "A"  # NSRDB PSM3 + pvlib. Track B (clear-sky) is NOT used unless
             # NSRDB_FALLBACK_TO_TRACK_B is explicitly set True, and every
             # run using it must say so in run_report.md (Section 5 rule).
NSRDB_FALLBACK_TO_TRACK_B = False

# --------------------------------------------------------------------------
# Commercial
# --------------------------------------------------------------------------
PPA_USD_PER_MWH = 40.0  # FIXED by Carlos, August 2026

# --------------------------------------------------------------------------
# Physical model constants (Section 6)
# --------------------------------------------------------------------------
GAMMA_TEMP_COEFF = {  # per degC
    "crystalline_silicon": -0.0037,
    "cdte": -0.0028,
    # thin film other, Mixed, a-Si -> use crystalline_silicon, tag the site
}
DEGRADATION_RATE_ANNUAL = {  # d, /yr, used as the FIXED structural prior
    "crystalline_silicon": 0.005,
    "cdte": 0.004,
}
STATIC_LOSS_STACK = 0.86          # L: soiling, mismatch, wiring, IAM, availability
INVERTER_EFFICIENCY = 0.985       # eta_inv
COMMISSIONING_RAMP_EXCLUSION_YEARS = 0.5  # tau < this -> excluded

# Faiman cell-temperature model defaults (pvlib documented defaults)
FAIMAN_U0 = 25.0
FAIMAN_U1 = 6.84

# --------------------------------------------------------------------------
# PI / PRI decision thresholds
# --------------------------------------------------------------------------
PI_PRI_DECISION_THRESHOLD = 0.92
PEER_HEALTH_FLOOR_PI = 0.85
PEER_SET_TARGET = 15
PEER_MINIMUM = 4
ADAPTIVE_RADIUS_LADDER_KM = [150, 250, 400, 600]
PEER_AGE_WINDOW_YEARS = 4
PEER_DCAC_WINDOW = 0.20

MIN_SCOREABLE_MONTHS_PER_SITE_YEAR = 6
EPISODE_GAP_TOLERANCE_MONTHS = 1

# PRI_P75 is NOT hardcoded - it is computed from this fleet at runtime
# (Section 6: "the methodology observed 1.056 on a different fleet. Do not
# hardcode."). See s9_dollars.compute_pri_p75().
PRI_P75_REFERENCE_OTHER_FLEET = 1.056  # for comparison/sanity only, never used directly

# --------------------------------------------------------------------------
# Warranty defaults - ASSUMED, not contractual (Section 6 / S7e)
# --------------------------------------------------------------------------
WARRANTY_DEFAULTS_YEARS = {
    "epc_workmanship": 2.0,
    "inverter_min": 5.0,
    "inverter_max": 10.0,
    "module_product_min": 10.0,
    "module_product_max": 12.0,
    "module_performance": 25.0,
}
WARRANTY_URGENT_THRESHOLD_YEARS = 0.5  # < 6 months remaining

# --------------------------------------------------------------------------
# D-Band fault classifier (Fault Estimation Tracker, restated at S6)
# --------------------------------------------------------------------------
D_NOISE_CEILING = 0.03       # D < this -> NONE
D_WATCH_BAND_HIGH = 0.08     # noise <= D < this -> watch, not a fault
D_FAULT_FLOOR = 0.08         # D >= this -> classify (== score < 0.92, by design)
D_OUTAGE_FLOOR = 0.70

# Gate G1 - curtailment
G1_BA_MEDIAN_SCORE_CEILING = 0.92
G1_SITE_TO_BA_TOLERANCE = 0.10
G1_MIN_PLANTS_IN_BA_MONTH = 3

# Gate G2 - snow
G2_SNOW_LATITUDE_FLOOR = 37.0
G2_SNOW_MONTHS = [11, 12, 1, 2, 3]
G2_SUMMER_HEALTH_FLOOR = 0.95
G2_SUMMER_MONTHS = [4, 5, 6, 7, 8, 9, 10]

# Gate G3 - clipping
G3_CLIPPING_DCAC_FLOOR = 1.35
G3_CLIPPING_MONTHS = [4, 5, 6, 7, 8]
G3_CLIPPING_PRI_FLOOR = 0.95

# Block-fraction discriminator
BLOCK_FLAT_STD_TOLERANCE = 0.05
BLOCK_STEP_ONSET_RISE = 0.08
BLOCK_FRACTION_TOLERANCE = 0.03  # nearest match, not first-within-tolerance

BLOCK_FRACTION_TABLE = [
    (0.042, "1/24"), (0.050, "1/20"), (0.063, "1/16"), (0.083, "1/12"),
    (0.100, "1/10"), (0.111, "1/9"), (0.125, "1/8"), (0.143, "1/7"),
    (0.167, "1/6"), (0.200, "1/5"), (0.222, "2/9"), (0.250, "1/4"),
    (0.286, "2/7"), (0.300, "3/10"), (0.333, "1/3"), (0.375, "3/8"),
    (0.400, "2/5"), (0.417, "5/12"), (0.500, "1/2"), (0.667, "2/3"),
    (0.750, "3/4"),
]

# Soiling discriminator
SOILING_RISE_MIN_MONTHS = 3
SOILING_RISE_MIN_TOTAL = 0.06
SOILING_RESET_DROP_MIN = 0.05

# Tracker discriminator
TRACKER_DAYLIGHT_CORR_FLOOR = 0.50

# Degradation discriminator
DEGRADATION_PERSISTENCE_MONTHS = 8
DEGRADATION_PERSISTENCE_CV_CEILING = 0.35
DEGRADATION_YOY_DECLINE_PCT = 0.015  # > 1.5%/yr

# BOS discriminator
BOS_DISPERSION_CV_FLOOR = 0.50
BOS_SPIKE_D_FLOOR = 0.15
BOS_SPIKE_MIN_MONTHS = 2  # non-consecutive

# Discriminator scoring (Step 4)
DISCRIMINATOR_SCORES = {
    "BLOCK_flat_fraction": 3,
    "BLOCK_step_onset": 2,
    "SOILING_monotonic_rise": 3,
    "SOILING_reset_drop": 2,
    "TRACKER_daylight_corr": 3,
    "TRACKER_single_axis": 1,
    "DEGRADATION_persistence": 3,
    "DEGRADATION_yoy_decline": 2,
    "BOS_dispersion": 3,
    "BOS_nonconsecutive_spikes": 2,
    "OUTAGE_single_month": 5,
}
SIGNATURE_TIE_BREAK = ["OUTAGE", "BLOCK", "SOILING", "TRACKER", "DEGRADATION", "BOS"]
MINIMUM_WINNING_SCORE = 3

# Confidence (Step 5)
CONFIDENCE_HIGH_MIN_SCORE = 5
CONFIDENCE_HIGH_MIN_HEALTHY_PEERS = 8
CONFIDENCE_HIGH_MIN_YEARS = 2
CONFIDENCE_MEDIUM_MIN_SCORE = 3
CONFIDENCE_MEDIUM_MAX_SCORE = 4
CONFIDENCE_MEDIUM_MIN_HEALTHY_PEERS = 4

# Action map / recovery fractions (Step 6). PLACEHOLDERS, no ground truth yet.
SIGNATURE_ACTION_MAP = {
    "OUTAGE_FULL":       dict(rec_pct=0.90, inspection="SCADA + substation service",       preventative=False, wear_class="infant_mortality"),
    "BLOCK_OUTAGE":      dict(rec_pct=0.90, inspection="String/combiner IV + inverter",     preventative=True,  wear_class="wear_out"),
    "SOILING":           dict(rec_pct=0.85, inspection="Soiling station + clean trial",     preventative=True,  wear_class="schedule"),
    "TRACKER":           dict(rec_pct=0.80, inspection="Alignment survey + controller",     preventative=False, wear_class="infant_mortality"),
    "BOS_INTERMITTENT":  dict(rec_pct=0.70, inspection="Aerial IR + string IV trace",        preventative=True,  wear_class="wear_out"),
    "DEGRADATION":       dict(rec_pct=0.30, inspection="EL imaging + IV + PID test",         preventative=False, wear_class="capex_cycle"),
    "UNATTRIBUTED":      dict(rec_pct=0.35, inspection="Full site diagnostic",               preventative=None,  wear_class=None),
    "CURTAILMENT":       dict(rec_pct=0.00, inspection="none - commercial",                  preventative=None,  wear_class=None),
    "SNOW":              dict(rec_pct=0.00, inspection="none - weather",                     preventative=None,  wear_class=None),
    "CLIPPING":          dict(rec_pct=0.00, inspection="none - design",                      preventative=None,  wear_class=None),
    "NONE":              dict(rec_pct=0.00, inspection="",                                   preventative=None,  wear_class=None),
}
ZERO_RECOVERY_SIGNATURES = {"CURTAILMENT", "SNOW", "CLIPPING"}  # NEVER > 0. Guardrail.

FAULT_LEDGER_SIGNATURES = {"OUTAGE_FULL", "BLOCK_OUTAGE", "SOILING", "TRACKER",
                            "BOS_INTERMITTENT", "UNATTRIBUTED"}
EXPOSURE_LEDGER_SIGNATURES = {"CURTAILMENT", "SNOW", "CLIPPING"}
STATE_LEDGER_SIGNATURES = {"DEGRADATION"}

# --------------------------------------------------------------------------
# Section 0 interpretation defaults (named flags, per the brief's instruction
# to "implement the default, make it a named config flag, put it in front of
# Carlos")
# --------------------------------------------------------------------------
FLAG_0_1_SCORE_FALLBACK_MODE = "PI_ADJ_REGIONAL_MEDIAN"   # score = PI / median(region, month) when no peer group
FLAG_0_2_DOLLAR_AUTHORITY = "PART8_P75"                    # authoritative $ ranks the call list; tracker formula shown as value_usd_quick
FLAG_0_2_CROSS_CHECK_TOLERANCE = 0.15
FLAG_0_3_WATCH_BAND_EXCLUDED_FROM_COUNTS = True             # 0.03<=D<0.08 -> fault_flag False, excluded from episodes/rates/dollars
FLAG_0_4_DISCRIMINATOR_EVAL_ORDER = ["OUTAGE", "BLOCK", "SOILING", "TRACKER", "DEGRADATION", "BOS"]
FLAG_0_5_BLOCK_FRACTION_MATCH = "NEAREST"                   # not first-within-tolerance
FLAG_0_6_G2_2026_WINTER = "BORROW_PRIOR_YEAR_APR_OCT"        # else snow_gate_unevaluated

# --------------------------------------------------------------------------
# Known data gaps to encode, not narrate (Section 4)
# --------------------------------------------------------------------------
YEAR_2022_IS_PARTIAL = True          # 224-site subset; treat absence as missing, never zero
YEAR_2026_MAX_MONTH = 5              # YTD Jan-May only
YEAR_2026_EXPOSURE_MONTHS_CAP = 5
LEAP_YEARS = {2020, 2024}
CALENDAR_HOURS = {
    2019: 8760, 2020: 8784, 2021: 8760, 2022: 8760, 2023: 8760,
    2024: 8784, 2025: 8760,
}
CALENDAR_HOURS_2026_YTD = 3624  # Jan-May

DCAC_VALID_RANGE = (1.05, 1.65)
CAPACITY_NAME_MATCH_TOLERANCE = 0.10  # reported AC vs site_master.mwac

# --------------------------------------------------------------------------
# NSRDB pull (Section 5)
# --------------------------------------------------------------------------
NSRDB_GRID_DEG = 0.04  # ~4km grid, used to bucket sites onto shared cells
NSRDB_YEARS = list(range(2019, 2027))
NSRDB_ATTRIBUTES = ["ghi", "dni", "dhi", "air_temperature", "wind_speed", "surface_albedo"]
NSRDB_INTERVAL_MIN = 60
NSRDB_LEAP_DAY = True
NSRDB_TIME_CONVENTION = "LOCAL_STANDARD_TIME"  # no DST
NSRDB_CACHE_DIR = "nsrdb_cache"

# --------------------------------------------------------------------------
# Reconciliation targets (Section 4) - used by tests
# --------------------------------------------------------------------------
FUNNEL_EXPECTED = [
    ("start", 7359),
    ("drop_hybrid", 7204),
    ("require_latlon", 6974),
    ("require_mwdc_gt0", 6419),
    ("require_op_year", 6419),
    ("require_dcac_range", 6204),
]
ANNUAL_TOTALS_MWH_EXPECTED = {
    2019: 68_611_474, 2020: 85_979_097, 2021: 111_896_359, 2022: 12_961_245,
    2023: 162_330_524, 2024: 215_425_229, 2025: 290_808_705, "2026 YTD": 110_195_267,
}

RANDOM_SEED = 42
