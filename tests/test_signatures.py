"""Acceptance tests 15, 18, 19, 20 (Section 10), plus Section 0.5 block
fraction ambiguity handling."""
import pytest

import config
import s6_signatures as s6


# ---------------------------------------------------------------------------
# Band / watch band (acceptance test 20)
# ---------------------------------------------------------------------------

def test_noise_below_003():
    assert s6.band(0.02) == "NOISE"
    assert s6.fault_flag(0.02) is False


def test_watch_band_never_a_fault():
    """Acceptance test 20: no month with 0.03 <= D < 0.08 contributes an
    episode / rate / dollar (Section 0.3: recorded, but fault_flag=False)."""
    assert s6.fault_flag(0.03) is False
    assert s6.fault_flag(0.05) is False
    assert s6.fault_flag(0.079) is False


def test_fault_floor_at_008():
    assert s6.fault_flag(0.08) is True


# ---------------------------------------------------------------------------
# Gate precedence (acceptance test 15)
# ---------------------------------------------------------------------------

def test_gate_precedence_curtailment_beats_outage_band():
    """A site-month satisfying both G1 and the OUTAGE band (D >= 0.70,
    i.e. score <= 0.30) returns CURTAILMENT, not OUTAGE_FULL -- gates run
    first and stop classification entirely."""
    site_score = 0.30  # D = 0.70, squarely in the OUTAGE band
    result = s6.run_gates(
        site_score=site_score,
        ba_month_median_score=0.25,  # < 0.92, whole BA is depressed
        n_plants_in_ba_month=10,
        latitude=40.0,
        month_num=6,
        summer_mean_score=None,
        dcac=1.2,
        pri=None,
        benchmark_mode="peer",
    )
    assert result == "CURTAILMENT"
    assert s6.band(s6.deficit(site_score)) == "OUTAGE_FULL"  # would have looked like an outage


def test_gate_requires_minimum_plants():
    result = s6.run_gates(
        site_score=0.30, ba_month_median_score=0.25, n_plants_in_ba_month=2,
        latitude=40.0, month_num=6, summer_mean_score=None, dcac=1.2, pri=None,
        benchmark_mode="peer",
    )
    assert result is None  # only 2 plants in the BA-month, below the floor of 3


def test_g3_clipping_skipped_in_physical_mode():
    result = s6.gate_g3_clipping(dcac=1.5, month_num=6, pri=0.99, benchmark_mode="physical")
    assert result is False  # no peer group -> PRI can't be trusted for this gate


# ---------------------------------------------------------------------------
# Block fraction ambiguity (Section 0.5) and block guard (acceptance test 18)
# ---------------------------------------------------------------------------

def test_block_fraction_nearest_match_and_candidate_count():
    """At D=0.10 the candidates within +/-0.03 are 1/12, 1/10, 1/9, 1/8;
    the nearest is the exact match 1/10."""
    match = s6.block_fraction_lookup(0.10)
    assert match.fraction == "1/10"
    assert match.n_candidates == 4


def test_block_guard_fraction_alone_is_not_enough():
    """Acceptance test 18: no month is labelled BLOCK_OUTAGE on a fraction
    match alone -- the run must ALSO be flat and start with a step."""
    run_not_flat = s6.MonthlyRun(d_values=[0.10, 0.30, 0.02], prior_month_d=0.0)
    score = s6.block_score(run_not_flat)
    assert score < config.MIN_WINNING_SCORE  # fraction matched (mean~0.14->no) but not flat -> no +3
    run_flat_no_step = s6.MonthlyRun(d_values=[0.10, 0.10, 0.10], prior_month_d=0.09)
    score2 = s6.block_score(run_flat_no_step)
    assert score2 == 3  # flat + fraction match fires, but no step-onset points
    # +3 alone still requires the flat+fraction combination to have fired,
    # never fraction alone:
    run_no_flat_test = s6.MonthlyRun(d_values=[0.55], prior_month_d=0.0)  # single month, no run
    assert s6.block_score(run_no_flat_test) == 0


def test_block_flat_and_step_onset_stack():
    run = s6.MonthlyRun(d_values=[0.10, 0.10, 0.10], prior_month_d=0.0)  # jumped 0.10 from prior
    assert s6.block_score(run) == 5  # +3 flat/fraction, +2 step onset


# ---------------------------------------------------------------------------
# Confidence / LOW relabel (acceptance test 19)
# ---------------------------------------------------------------------------

def test_low_confidence_relabels_to_unattributed():
    """Acceptance test 19: no signature_final outside {UNATTRIBUTED, the
    three zero-recovery labels} carries confidence LOW."""
    inp = s6.ConfidenceInput(
        winning_score=3, n_healthy_peers=1, years_of_history=3,
        is_phased_build_in_window=False, scored_months_this_year=12,
        is_commissioning_ramp=False, benchmark_mode="peer",
    )
    level, reasons = s6.classify_confidence(inp)
    assert level == "LOW"  # score 3-4 but only 1 healthy peer, below MEDIUM's floor of 4
    final = s6.apply_low_confidence_relabel("BLOCK_OUTAGE", level)
    assert final == "UNATTRIBUTED"


def test_zero_recovery_signatures_survive_low_confidence():
    """Gate signatures never reach the discriminator step, so a LOW
    confidence label (which only applies to discriminator winners) must
    not relabel them away."""
    for sig in config.ZERO_RECOVERY_SIGNATURES:
        assert s6.apply_low_confidence_relabel(sig, "LOW") == sig


def test_confidence_downgrades_one_level_per_reason_not_per_flag():
    inp = s6.ConfidenceInput(
        winning_score=6, n_healthy_peers=10, years_of_history=3,
        is_phased_build_in_window=True, scored_months_this_year=12,
        is_commissioning_ramp=False, benchmark_mode="peer",
    )
    level, reasons = s6.classify_confidence(inp)
    assert level == "MEDIUM"  # HIGH downgraded once for the phased build
    assert reasons == ["phased_build_capacity_added"]


# ---------------------------------------------------------------------------
# Winner / tie-break
# ---------------------------------------------------------------------------

def test_winner_below_minimum_score_is_none():
    vec = s6.ScoreVector(scores={"OUTAGE": 0, "BLOCK": 2, "SOILING": 0, "TRACKER": 0, "DEGRADATION": 0, "BOS": 0})
    winner, score, runner, runner_score = vec.winner()
    assert winner is None
    assert s6.resolve_final_signature(winner) == "UNATTRIBUTED"


def test_tie_break_order():
    vec = s6.ScoreVector(scores={"OUTAGE": 0, "BLOCK": 3, "SOILING": 3, "TRACKER": 0, "DEGRADATION": 0, "BOS": 0})
    winner, score, runner, runner_score = vec.winner()
    assert winner == "BLOCK"  # BLOCK precedes SOILING in the tie-break order
    assert runner == "SOILING"
