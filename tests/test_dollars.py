"""Acceptance tests 9, 17, 21 (Section 10)."""
import pytest

import config
import s9_dollars as d9


def test_zero_recovery_signatures_never_move():
    """Acceptance test 9: rho for CURTAILMENT, SNOW, CLIPPING is exactly 0.00."""
    for sig in ("CURTAILMENT", "SNOW", "CLIPPING"):
        assert config.RECOVERY_FRACTION[sig] == 0.00


@pytest.mark.parametrize("signature", sorted(config.ZERO_RECOVERY_SIGNATURES))
def test_recoverable_is_zero_for_zero_recovery_signatures(signature):
    """Acceptance test 17, row level: recoverable_mwh = 0 for any gap on
    these signatures, regardless of how large the gap is."""
    assert d9.recoverable(g=999_999.0, signature=signature) == 0.0
    assert d9.value_usd(d9.recoverable(g=999_999.0, signature=signature)) == 0.0


def test_recoverable_nonzero_for_a_real_fault():
    assert d9.recoverable(g=100.0, signature="BLOCK_OUTAGE") == pytest.approx(90.0)


def test_tracker_worked_example_dollar_cross_check():
    """Acceptance test 21: D=0.25, SY_peer=150, DC=500 MW, BLOCK (90%),
    PPA=40 -> 675,000 USD for that month."""
    value = d9.value_usd_quick(d=0.25, sy_peer_median=150, dc_mw=500, signature="BLOCK_OUTAGE", ppa=40.0)
    assert value == pytest.approx(675_000.0)


def test_cross_check_passes_within_tolerance():
    d9.assert_cross_check(part8_usd=700_000, quick_usd=675_000)  # ~3.6% apart, must not raise


def test_cross_check_fails_outside_tolerance():
    with pytest.raises(AssertionError):
        d9.assert_cross_check(part8_usd=900_000, quick_usd=675_000)  # ~25% apart


def test_target_generation_falls_back_without_peers():
    t = d9.target_generation(peer_median_sy=None, pri_p75=1.05, p_dc=10, e_exp=1000, pi_p75=0.95)
    assert t == pytest.approx(950.0)


def test_target_generation_uses_peer_median_when_available():
    t = d9.target_generation(peer_median_sy=150, pri_p75=1.05, p_dc=500, e_exp=None, pi_p75=None)
    assert t == pytest.approx(150 * 1.05 * 500)


def test_gap_never_negative():
    assert d9.gap(target=100, e_act=150) == 0.0
    assert d9.gap(target=100, e_act=80) == 20.0
