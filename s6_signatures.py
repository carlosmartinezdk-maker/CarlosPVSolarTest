"""D-Band fault signature classifier (Fault Estimation Tracker).

Pure functions only -- no I/O, no pandas dependency required for the core
logic, so this module is fully unit-testable without the real production
data. s6_signatures_pipeline (not yet written -- needs S4/S7 outputs) will
wire these functions over the actual site-month panel.

Run-order note (brief Section 7, S6): the DEGRADATION discriminator needs
the S7 trajectory slope, so the full pipeline runs S7 before S6 despite the
numbering. That dependency is only at the pipeline-wiring level; the
functions here take the slope as a plain argument and don't care who
computed it or when.
"""
from __future__ import annotations

import statistics
from dataclasses import dataclass, field

import config


# ---------------------------------------------------------------------------
# Step 1 -- elimination gates
# ---------------------------------------------------------------------------

def gate_g1_curtailment(site_score: float, ba_month_median_score: float, n_plants_in_ba_month: int) -> bool:
    """REGIONAL -> CURTAILMENT."""
    if n_plants_in_ba_month < config.G1_MIN_PLANTS_IN_BA_MONTH:
        return False
    if ba_month_median_score >= config.G1_BA_MEDIAN_SCORE_CEILING:
        return False
    return abs(site_score - ba_month_median_score) <= config.G1_SITE_BA_TOLERANCE


def gate_g2_snow(latitude: float, month_num: int, summer_mean_score: float | None) -> bool:
    """WINTER -> SNOW. `summer_mean_score` is mean(score, Apr-Oct) for the
    relevant year, already resolved by the caller per Section 0.6 (2026
    winter months borrow the prior year's summer mean; if that's also
    missing, the caller passes None and this gate does not fire -- fall
    through to Step 2, tagged snow_gate_unevaluated by the caller)."""
    if latitude < config.G2_LATITUDE_FLOOR:
        return False
    if month_num not in config.G2_SNOW_MONTHS:
        return False
    if summer_mean_score is None:
        return False
    return summer_mean_score >= config.G2_SUMMER_HEALTH_FLOOR


def gate_g3_clipping(dcac: float, month_num: int, pri: float | None, benchmark_mode: str) -> bool:
    """DESIGN -> CLIPPING. Tests PRI specifically (needs a peer group);
    skip where benchmark_mode is 'physical' (no valid peer group)."""
    if benchmark_mode == "physical" or pri is None:
        return False
    if dcac < config.G3_DCAC_FLOOR:
        return False
    if month_num not in config.G3_CLIPPING_MONTHS:
        return False
    return pri >= config.G3_PRI_FLOOR


def run_gates(
    *,
    site_score: float,
    ba_month_median_score: float | None,
    n_plants_in_ba_month: int,
    latitude: float,
    month_num: int,
    summer_mean_score: float | None,
    dcac: float,
    pri: float | None,
    benchmark_mode: str,
) -> str | None:
    """First hit wins. Returns the gate signature or None if no gate fires."""
    if ba_month_median_score is not None and gate_g1_curtailment(site_score, ba_month_median_score, n_plants_in_ba_month):
        return "CURTAILMENT"
    if gate_g2_snow(latitude, month_num, summer_mean_score):
        return "SNOW"
    if gate_g3_clipping(dcac, month_num, pri, benchmark_mode):
        return "CLIPPING"
    return None


# ---------------------------------------------------------------------------
# Deficit and band
# ---------------------------------------------------------------------------

def deficit(score: float) -> float:
    """D = max(0, 1 - score). NOT 1 - PI; score is PRI where a valid peer
    group exists, else seasonally-calibrated PI (Section 0.1)."""
    return max(0.0, 1.0 - score)


def band(d: float) -> str:
    if d < config.D_NOISE_CEILING:
        return "NOISE"
    if d < config.D_FAULT_FLOOR:
        return "WATCH"
    if d < 0.15:
        return "SOILING/BLOCK/DEGRADATION/TRACKER/BOS"
    if d < 0.30:
        return "BLOCK/BOS/TRACKER/SOILING_SEVERE"
    if d < 0.50:
        return "BLOCK/BOS_SEVERE"
    if d < config.D_OUTAGE_FLOOR:
        return "BLOCK_PARTIAL_OUTAGE"
    return "OUTAGE_FULL"


def fault_flag(d: float) -> bool:
    """Section 0.3: D < 0.03 -> NONE (not recorded as fault). 0.03 <= D <
    0.08 -> recorded but fault_flag=False (watch band, excluded from
    episodes/rates/dollars). D >= 0.08 -> classified fault."""
    return d >= config.D_FAULT_FLOOR


# ---------------------------------------------------------------------------
# Step 3 -- block fraction lookup (sizing only, never causation)
# ---------------------------------------------------------------------------

@dataclass
class BlockFractionMatch:
    fraction: str | None
    n_candidates: int


def block_fraction_lookup(d: float) -> BlockFractionMatch:
    """Nearest match within tolerance, per Section 0.5 -- NOT the first
    match within tolerance. Also records n_candidates (how many table
    entries fall within +/- BLOCK_FRACTION_TOLERANCE of d), so the caller
    can show "4 candidates fit equally well" instead of implying certainty."""
    candidates = [
        (frac, abs(table_d - d))
        for table_d, frac in config.BLOCK_FRACTION_TABLE
        if abs(table_d - d) <= config.BLOCK_FRACTION_TOLERANCE
    ]
    if not candidates:
        return BlockFractionMatch(None, 0)
    nearest = min(candidates, key=lambda c: c[1])
    return BlockFractionMatch(nearest[0], len(candidates))


# ---------------------------------------------------------------------------
# Step 4 -- discriminators
# ---------------------------------------------------------------------------

@dataclass
class MonthlyRun:
    """A run of consecutive (gap-tolerant) deficit months for one site,
    used by the run-level and year-level discriminators (Section 0.4)."""
    d_values: list[float]
    prior_month_d: float | None = None


def block_score(run: MonthlyRun) -> int:
    """BLOCK: flat run matching a fraction (+3), or step onset (+2). Both
    can fire on the same run and stack (spec: 'sum by signature')."""
    if len(run.d_values) < 2:
        return 0
    points = 0
    is_flat = statistics.pstdev(run.d_values) < config.BLOCK_FLAT_STD_TOLERANCE
    mean_d = statistics.mean(run.d_values)
    match = block_fraction_lookup(mean_d)
    if is_flat and match.fraction is not None:
        points += 3
    if run.prior_month_d is not None and (run.d_values[0] - run.prior_month_d) >= config.BLOCK_STEP_ONSET_RISE:
        points += 2
    return points


def soiling_score(monthly_d_in_order: list[float]) -> int:
    """SOILING: monotonic rise >= 3 months with total rise >= 0.06 (+3),
    plus a reset drop >= 0.05 the month after (+2)."""
    if len(monthly_d_in_order) < config.SOILING_RISE_MIN_MONTHS:
        return 0
    points = 0
    rise_run = monthly_d_in_order[: config.SOILING_RISE_MIN_MONTHS]
    is_monotonic = all(b >= a for a, b in zip(rise_run, rise_run[1:]))
    total_rise = rise_run[-1] - rise_run[0]
    if is_monotonic and total_rise >= config.SOILING_RISE_MIN_TOTAL:
        points += 3
        if len(monthly_d_in_order) > config.SOILING_RISE_MIN_MONTHS:
            drop = rise_run[-1] - monthly_d_in_order[config.SOILING_RISE_MIN_MONTHS]
            if drop >= config.SOILING_RESET_DROP_MIN:
                points += 2
    return points


def tracker_score(yearly_d: list[float], yearly_daylight_hours: list[float], is_single_axis: bool) -> int:
    """TRACKER: corr(D, daylight hours) >= 0.50 across the year (+3), plus
    +1 if the site is single-axis."""
    points = 0
    if len(yearly_d) >= 3 and len(yearly_d) == len(yearly_daylight_hours):
        corr = _pearson(yearly_d, yearly_daylight_hours)
        if corr is not None and corr >= config.TRACKER_DAYLIGHT_CORR_MIN:
            points += 3
    if is_single_axis:
        points += 1
    return points


def degradation_score(yearly_d: list[float], yoy_pi_decline_pct: float | None) -> int:
    """DEGRADATION: D >= 0.05 in >= 8 months AND CV(D) < 0.35 (+3), plus
    year-on-year PI decline > 1.5%/yr from the S7 trajectory slope (+2)."""
    points = 0
    months_over_threshold = sum(1 for d in yearly_d if d >= 0.05)
    if months_over_threshold >= config.DEGRADATION_MIN_MONTHS and len(yearly_d) > 0:
        mean_d = statistics.mean(yearly_d)
        cv = (statistics.pstdev(yearly_d) / mean_d) if mean_d > 0 else float("inf")
        if cv < config.DEGRADATION_CV_CEILING:
            points += 3
    if yoy_pi_decline_pct is not None and yoy_pi_decline_pct > config.DEGRADATION_YOY_DECLINE_PCT:
        points += 2
    return points


def bos_score(yearly_d: list[float]) -> int:
    """BOS: CV(monthly D) >= 0.50 with no seasonal/step pattern (+3), plus
    >= 2 non-consecutive months with D >= 0.15 (+2)."""
    points = 0
    if len(yearly_d) > 0:
        mean_d = statistics.mean(yearly_d)
        cv = (statistics.pstdev(yearly_d) / mean_d) if mean_d > 0 else float("inf")
        if cv >= config.BOS_CV_FLOOR:
            points += 3
    spike_months = [i for i, d in enumerate(yearly_d) if d >= config.BOS_SPIKE_D_FLOOR]
    non_consecutive = _count_non_consecutive(spike_months)
    if non_consecutive >= config.BOS_MIN_NONCONSECUTIVE_SPIKE_MONTHS:
        points += 2
    return points


def outage_score(month_d: float) -> int:
    """OUTAGE: D >= 0.70 in this single month (+5)."""
    return 5 if month_d >= config.D_OUTAGE_FLOOR else 0


@dataclass
class ScoreVector:
    scores: dict = field(default_factory=lambda: {"OUTAGE": 0, "BLOCK": 0, "SOILING": 0, "TRACKER": 0, "DEGRADATION": 0, "BOS": 0})

    def winner(self) -> tuple[str | None, int, str | None, int]:
        """Returns (winning_signature, winning_score, runner_up, runner_up_score).
        Ties broken per config.SIGNATURE_TIE_BREAK order."""
        ranked = sorted(
            self.scores.items(),
            key=lambda kv: (-kv[1], config.SIGNATURE_TIE_BREAK.index(kv[0])),
        )
        top_sig, top_score = ranked[0]
        if top_score < config.MIN_WINNING_SCORE:
            return None, top_score, None, 0
        runner_sig, runner_score = (ranked[1] if len(ranked) > 1 else (None, 0))
        return top_sig, top_score, runner_sig, runner_score


BAND_TO_SIGNATURE = {
    "OUTAGE_FULL": "OUTAGE_FULL",
    "BLOCK": "BLOCK_OUTAGE",
    "SOILING": "SOILING",
    "TRACKER": "TRACKER",
    "DEGRADATION": "DEGRADATION",
    "BOS": "BOS_INTERMITTENT",
}


def resolve_final_signature(winner_key: str | None) -> str:
    """Map the Step 4 winning discriminator key to the S6 output signature
    name used everywhere else (action map, ledgers, rho lookup)."""
    if winner_key is None:
        return "UNATTRIBUTED"
    return BAND_TO_SIGNATURE.get(winner_key, "UNATTRIBUTED")


# ---------------------------------------------------------------------------
# Step 5 -- confidence
# ---------------------------------------------------------------------------

@dataclass
class ConfidenceInput:
    winning_score: int
    n_healthy_peers: int
    years_of_history: float
    is_phased_build_in_window: bool
    scored_months_this_year: int
    is_commissioning_ramp: bool
    benchmark_mode: str  # "peer" | "physical"


def classify_confidence(inp: ConfidenceInput) -> tuple[str, list[str]]:
    if (
        inp.winning_score >= config.CONFIDENCE_HIGH_MIN_SCORE
        and inp.n_healthy_peers >= config.CONFIDENCE_HIGH_MIN_HEALTHY_PEERS
        and inp.years_of_history >= config.CONFIDENCE_HIGH_MIN_YEARS
    ):
        level = "HIGH"
    elif (
        config.CONFIDENCE_MEDIUM_MIN_SCORE <= inp.winning_score
        and inp.n_healthy_peers >= config.CONFIDENCE_MEDIUM_MIN_HEALTHY_PEERS
    ):
        level = "MEDIUM"
    else:
        level = "LOW"

    downgrade_reasons = []
    if inp.is_phased_build_in_window:
        downgrade_reasons.append("phased_build_capacity_added")
    if inp.scored_months_this_year < config.MIN_SCOREABLE_MONTHS_PER_SITE_YEAR:
        downgrade_reasons.append("fewer_than_6_scored_months")
    if inp.is_commissioning_ramp:
        downgrade_reasons.append("commissioning_ramp")
    if inp.benchmark_mode == "physical":
        downgrade_reasons.append("physical_benchmark_mode")

    if downgrade_reasons:
        level = {"HIGH": "MEDIUM", "MEDIUM": "LOW", "LOW": "LOW"}[level]

    return level, downgrade_reasons


def apply_low_confidence_relabel(signature_raw: str, confidence: str) -> str:
    """A LOW result is relabelled to UNATTRIBUTED (recovery 35%), routed to
    full diagnostic. Zero-recovery gate signatures (CURTAILMENT/SNOW/
    CLIPPING) are not touched -- they never reach the discriminator step."""
    if signature_raw in config.ZERO_RECOVERY_SIGNATURES:
        return signature_raw
    return "UNATTRIBUTED" if confidence == "LOW" else signature_raw


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------

def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2:
        return None
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    cov = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    var_x = sum((x - mean_x) ** 2 for x in xs)
    var_y = sum((y - mean_y) ** 2 for y in ys)
    if var_x == 0 or var_y == 0:
        return None
    return cov / math_sqrt(var_x * var_y)


def math_sqrt(x: float) -> float:
    return x ** 0.5


def _count_non_consecutive(indices: list[int]) -> int:
    """Count spike months, collapsing any run of consecutive indices to 1
    (a run is one contiguous event, not N separate spikes)."""
    if not indices:
        return 0
    count = 1
    for a, b in zip(indices, indices[1:]):
        if b != a + 1:
            count += 1
    return count
