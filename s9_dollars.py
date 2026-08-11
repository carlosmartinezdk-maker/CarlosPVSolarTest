"""Index-to-dollars conversion (Part 8 / S9), plus the tracker's quick
cross-check (Section 0.2). Pure functions -- no I/O.
"""
from __future__ import annotations

import config


def target_generation(
    *,
    peer_median_sy: float | None,
    pri_p75: float,
    p_dc: float,
    e_exp: float | None,
    pi_p75: float | None,
) -> float:
    """S9a: T(i,m) = median(SY_peer) x PRI_P75 x P_dc, with peers.
    No peer group: T(i,m) = E_exp x PI_P75."""
    if peer_median_sy is not None:
        return peer_median_sy * pri_p75 * p_dc
    if e_exp is None or pi_p75 is None:
        raise ValueError("No peer group and no (E_exp, PI_P75) fallback available.")
    return e_exp * pi_p75


def gap(target: float, e_act: float) -> float:
    """S9b: G(i,m) = max(T - E_act, 0)."""
    return max(target - e_act, 0.0)


def recoverable(g: float, signature: str) -> float:
    """S9c: R(i,m) = G(i,m) * rho_s.

    GUARDRAIL: CURTAILMENT, SNOW, and CLIPPING carry rho = 0.00 by
    definition (config.ZERO_RECOVERY_SIGNATURES). This function does not
    special-case them -- it trusts config.RECOVERY_FRACTION, which is
    exactly why tests/test_dollars.py asserts those three entries stay
    0.00. If that assertion ever fails, something has made curtailment
    look recoverable, and that is the single most damaging change anyone
    could make to this pipeline (brief, S9).
    """
    rho = config.RECOVERY_FRACTION[signature]
    return g * rho


def value_usd(r: float, ppa: float = config.PPA_USD_PER_MWH) -> float:
    """S9d: $(i,m) = R(i,m) * PPA."""
    return r * ppa


def value_usd_quick(
    *, d: float, sy_peer_median: float, dc_mw: float, signature: str, ppa: float = config.PPA_USD_PER_MWH
) -> float:
    """Tracker's quick estimate (Section 0.2): $ = D x SY_peer x DC x REC% x PPA.
    Uses peer MEDIAN as its benchmark (vs. Part 8's P75). Shown alongside
    the authoritative Part 8 figure in the explorer; the two should stay
    within 15% of each other (assert_cross_check)."""
    rho = config.RECOVERY_FRACTION[signature]
    return d * sy_peer_median * dc_mw * rho * ppa


def assert_cross_check(part8_usd: float, quick_usd: float, tolerance: float = 0.15) -> None:
    """S9e: Part 8 and the tracker's quick estimate should stay within 15%
    of each other. A wider gap points at a peer-set problem, not a
    rounding difference -- this is a hard assertion, not a warning."""
    if part8_usd == 0 and quick_usd == 0:
        return
    denom = max(abs(part8_usd), abs(quick_usd), 1e-9)
    divergence = abs(part8_usd - quick_usd) / denom
    if divergence > tolerance:
        raise AssertionError(
            f"Part 8 (${part8_usd:,.2f}) and quick estimate (${quick_usd:,.2f}) "
            f"diverge by {divergence:.1%}, exceeding the {tolerance:.0%} "
            f"tolerance -- investigate the peer set before trusting either figure."
        )
