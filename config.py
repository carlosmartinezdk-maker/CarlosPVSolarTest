"""All constants for the PI/PRI solar underperformance pipeline.

Source of truth: CLAUDE_CODE_BRIEF_PI_PRI_Analysis_1.md (v2, 2019-2026 panel).
Nothing in this module is inline elsewhere in the pipeline.
"""
from __future__ import annotations

import os

# ---------------------------------------------------------------------------
# Commercial
# ---------------------------------------------------------------------------

PPA_USD_PER_MWH = 40.0  # FIXED, set by Carlos, August 2026

# ---------------------------------------------------------------------------
# Physical constants
# ---------------------------------------------------------------------------

# temperature coefficient, /degC. c-Si default; CdTe overrides.
GAMMA_CSI = -0.0037
GAMMA_CDTE = -0.0028
# Mixed / other thin film use c-Si and are tagged `gamma_assumed = True`.

# annual degradation rate, /yr, used as the FIXED prior in S7 (never fit
# unconstrained -- age/cohort/calendar-period are collinear).
DEGRADATION_RATE_CSI = 0.005
DEGRADATION_RATE_CDTE = 0.004

STATIC_LOSS_STACK = 0.86  # soiling, mismatch, wiring, IAM, availability
INVERTER_EFFICIENCY = 0.985

# ---------------------------------------------------------------------------
# Index / decision thresholds
# ---------------------------------------------------------------------------

PI_PRI_DECISION_THRESHOLD = 0.92
PEER_HEALTH_FLOOR_PI = 0.85
PEER_SET_TARGET = 15
PEER_MINIMUM = 4  # below this: no PRI, PI alone
PEER_AGE_WINDOW_YEARS = 4
PEER_DCAC_WINDOW = 0.20
ADAPTIVE_RADIUS_LADDER_KM = (150, 250, 400, 600)
COMMISSIONING_RAMP_EXCLUSION_YEARS = 0.5
MIN_SCOREABLE_MONTHS_PER_SITE_YEAR = 6
EPISODE_GAP_TOLERANCE_MONTHS = 1

# PRI_P75 is NOT hardcoded -- compute the 0.75 quantile of PRI from this
# fleet's own data (S9a). The methodology's reference value (1.056) is a
# check, not an input.
PRI_P75_REFERENCE_ONLY = 1.056

# Warranty defaults -- ASSUMED, not contractual. Tag every warranty output
# accordingly.
WARRANTY_EPC_YEARS = 2
WARRANTY_INVERTER_YEARS_MIN = 5
WARRANTY_INVERTER_YEARS_MAX = 10
WARRANTY_MODULE_PRODUCT_YEARS_MIN = 10
WARRANTY_MODULE_PRODUCT_YEARS_MAX = 12
WARRANTY_MODULE_PERFORMANCE_YEARS = 25
WARRANTY_URGENT_MONTHS_REMAINING = 6

# ---------------------------------------------------------------------------
# Data-quality gates (S1) -- Section 4 funnel
# ---------------------------------------------------------------------------

DCAC_VALID_RANGE = (1.05, 1.65)
NAME_JOIN_CAPACITY_TOLERANCE = 0.10  # +/-10% vs site_master.mwac

# ---------------------------------------------------------------------------
# NSRDB / NLR request constants (S2)
# ---------------------------------------------------------------------------

NLR_BASE_URL = "https://developer.nlr.gov"
NLR_NSRDB_ENDPOINT = "/api/nsrdb/v2/solar/nsrdb-GOES-aggregated-v4-0-0-download.csv"

# Read from NLR_API_KEY, falling back to NREL_API_KEY for older shells.
# NEVER hardcode, NEVER commit, NEVER log, NEVER embed in any output artifact.
def get_api_key() -> str:
    key = os.environ.get("NLR_API_KEY") or os.environ.get("NREL_API_KEY")
    if not key:
        raise RuntimeError(
            "No API key found. Set NLR_API_KEY (or NREL_API_KEY) in the "
            "environment. Never pass it as a literal or CLI argument -- it "
            "would land in shell history and process listings."
        )
    return key


NLR_REQUEST_ATTRIBUTES = "ghi,dni,dhi,air_temperature,wind_speed,surface_albedo"
NLR_INTERVAL = 60  # minutes; API accepts 30 or 60
NLR_UTC = False  # API default is True -- we need local standard time
NLR_LEAP_DAY = True  # API default is False -- would silently drop Feb 29

NSRDB_YEARS_AVAILABLE = tuple(range(1998, 2026))  # 1998-2025 inclusive, no 2026
SCORED_YEARS_WITH_IRRADIANCE = tuple(range(2019, 2026))  # 2019-2025
GRID_RESOLUTION_KM = 4

NLR_CSV_RATE_LIMIT_PER_DAY = 10_000
NLR_CSV_MIN_SECONDS_BETWEEN_REQUESTS = 1.0
NLR_MAX_CONCURRENT_REQUESTS = 20

NLR_ALLOWLIST_HOSTS = (
    "developer.nlr.gov",  # the NSRDB API itself -- required
    "mapfiles.nlr.gov",  # async .json archive downloads -- optional
    "data.openei.org",  # bulk S3 mirror index -- optional
    "nrel-pds-nsrdb.s3.amazonaws.com",  # bulk NSRDB objects -- optional
    "nsrdb.nlr.gov",  # announcements page -- optional
)

# ---------------------------------------------------------------------------
# D-Band classifier constants (S6) -- Fault Estimation Tracker
# ---------------------------------------------------------------------------

D_NOISE_CEILING = 0.03  # D < this -> NONE
D_WATCH_FLOOR = 0.03
D_WATCH_CEILING = 0.08  # 0.03 <= D < this -> recorded, fault_flag=False
D_FAULT_FLOOR = 0.08  # D >= this -> classify
D_OUTAGE_FLOOR = 0.70

# G1 curtailment
G1_BA_MEDIAN_SCORE_CEILING = 0.92
G1_SITE_BA_TOLERANCE = 0.10
G1_MIN_PLANTS_IN_BA_MONTH = 3

# G2 snow
G2_LATITUDE_FLOOR = 37.0
G2_SNOW_MONTHS = (11, 12, 1, 2, 3)
G2_SUMMER_MONTHS = (4, 5, 6, 7, 8, 9, 10)
G2_SUMMER_HEALTH_FLOOR = 0.95

# G3 clipping
G3_DCAC_FLOOR = 1.35
G3_CLIPPING_MONTHS = (4, 5, 6, 7, 8)
G3_PRI_FLOOR = 0.95

# Block
BLOCK_FLAT_STD_TOLERANCE = 0.05
BLOCK_STEP_ONSET_RISE = 0.08
BLOCK_FRACTION_TOLERANCE = 0.03  # nearest match, not first-within-tolerance

# Ordered (D, fraction) lookup table -- Step 3.
BLOCK_FRACTION_TABLE = (
    (0.042, "1/24"), (0.050, "1/20"), (0.063, "1/16"), (0.083, "1/12"),
    (0.100, "1/10"), (0.111, "1/9"), (0.125, "1/8"), (0.143, "1/7"),
    (0.167, "1/6"), (0.200, "1/5"), (0.222, "2/9"), (0.250, "1/4"),
    (0.286, "2/7"), (0.300, "3/10"), (0.333, "1/3"), (0.375, "3/8"),
    (0.400, "2/5"), (0.417, "5/12"), (0.500, "1/2"), (0.667, "2/3"),
    (0.750, "3/4"),
)

# Soiling
SOILING_RISE_MIN_MONTHS = 3
SOILING_RISE_MIN_TOTAL = 0.06
SOILING_RESET_DROP_MIN = 0.05

# Tracker
TRACKER_DAYLIGHT_CORR_MIN = 0.50

# Degradation
DEGRADATION_MIN_MONTHS = 8
DEGRADATION_CV_CEILING = 0.35
DEGRADATION_YOY_DECLINE_PCT = 0.015  # > 1.5%/yr

# BOS
BOS_CV_FLOOR = 0.50
BOS_MIN_NONCONSECUTIVE_SPIKE_MONTHS = 2
BOS_SPIKE_D_FLOOR = 0.15

# Discriminator point values (Step 4)
DISCRIMINATOR_POINTS = {
    "block_flat_and_fraction": ("BLOCK", 3),
    "block_step_onset": ("BLOCK", 2),
    "soiling_monotonic_rise": ("SOILING", 3),
    "soiling_reset_drop": ("SOILING", 2),
    "tracker_daylight_corr": ("TRACKER", 3),
    "tracker_single_axis": ("TRACKER", 1),
    "degradation_persistence": ("DEGRADATION", 3),
    "degradation_trajectory": ("DEGRADATION", 2),
    "bos_dispersion": ("BOS", 3),
    "bos_spikes": ("BOS", 2),
    "outage_single_month": ("OUTAGE", 5),
}

SIGNATURE_TIE_BREAK = ("OUTAGE", "BLOCK", "SOILING", "TRACKER", "DEGRADATION", "BOS")
MIN_WINNING_SCORE = 3  # below this -> UNATTRIBUTED

# Confidence
CONFIDENCE_HIGH_MIN_SCORE = 5
CONFIDENCE_HIGH_MIN_HEALTHY_PEERS = 8
CONFIDENCE_HIGH_MIN_YEARS = 2
CONFIDENCE_MEDIUM_MIN_SCORE = 3
CONFIDENCE_MEDIUM_MIN_HEALTHY_PEERS = 4

# Action map: signature -> (recovery fraction, preventative?)
# The three zero-recovery signatures are a credibility guardrail -- see
# tests/test_dollars.py::test_zero_recovery_signatures_never_move. Never
# make CURTAILMENT, SNOW, or CLIPPING recoverable.
RECOVERY_FRACTION = {
    "OUTAGE_FULL": 0.90,
    "BLOCK_OUTAGE": 0.90,
    "SOILING": 0.85,
    "TRACKER": 0.80,
    "BOS_INTERMITTENT": 0.70,
    "DEGRADATION": 0.30,
    "UNATTRIBUTED": 0.35,
    "CURTAILMENT": 0.00,
    "SNOW": 0.00,
    "CLIPPING": 0.00,
}

PREVENTATIVE_ELIGIBLE = {
    "OUTAGE_FULL": False,  # infant mortality
    "BLOCK_OUTAGE": True,  # wear-out
    "SOILING": True,  # schedule
    "TRACKER": False,  # infant mortality
    "BOS_INTERMITTENT": True,  # wear-out
    "DEGRADATION": False,  # capex cycle
    "UNATTRIBUTED": None,
    "CURTAILMENT": None,
    "SNOW": None,
    "CLIPPING": None,
}

ZERO_RECOVERY_SIGNATURES = frozenset({"CURTAILMENT", "SNOW", "CLIPPING"})

CLASSIFIER_VERSION = "d-band-v2"
