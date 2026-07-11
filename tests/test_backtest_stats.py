"""Tests for the from-scratch backtest stats."""
from __future__ import annotations

import math

import pytest

from defi_investor.backtest.stats import (
    average_uniqueness,
    bet_stats,
    hhi,
    psr,
)


# --- bet_stats -------------------------------------------------------------


def test_bet_stats_positive_edge_reports_positive_psr():
    rs = [0.10, 0.20, 0.15, -0.05, 0.30, 0.25, -0.10, 0.40]
    s = bet_stats(rs)
    assert s is not None
    assert s.n == 8
    assert s.mean_r > 0
    assert s.sharpe > 0
    assert 0.5 < s.psr_vs_zero <= 1.0


def test_bet_stats_returns_none_on_constant_series():
    """Zero stdev — Sharpe undefined, refuse to fabricate a number."""
    assert bet_stats([0.0] * 10) is None


def test_bet_stats_returns_none_on_tiny_sample():
    assert bet_stats([]) is None
    assert bet_stats([0.5]) is None


# --- psr -------------------------------------------------------------------


def test_psr_indifference_at_benchmark():
    """When observed SR == benchmark, PSR should be exactly 0.5."""
    assert psr(sharpe=0.0, n=100, skew=0, kurt=3, benchmark_sr=0.0) == pytest.approx(0.5, abs=1e-9)


def test_psr_grows_toward_one_with_edge_and_sample_size():
    p = psr(sharpe=0.5, n=1000, skew=0, kurt=3, benchmark_sr=0.0)
    assert p > 0.99


def test_psr_negative_edge_is_below_half():
    p = psr(sharpe=-0.3, n=100, skew=0, kurt=3, benchmark_sr=0.0)
    assert p < 0.5


def test_psr_negative_skew_penalizes_the_same_sharpe():
    """Negative skew increases the variance of the SR estimator."""
    baseline = psr(sharpe=0.3, n=100, skew=0.0, kurt=3, benchmark_sr=0.0)
    negskew = psr(sharpe=0.3, n=100, skew=-1.0, kurt=3, benchmark_sr=0.0)
    assert negskew < baseline


def test_psr_high_kurtosis_penalizes():
    """Fat tails increase the estimator variance."""
    baseline = psr(sharpe=0.3, n=100, skew=0.0, kurt=3, benchmark_sr=0.0)
    fat = psr(sharpe=0.3, n=100, skew=0.0, kurt=8, benchmark_sr=0.0)
    assert fat < baseline


def test_psr_tiny_sample_returns_half_not_a_fake_number():
    assert psr(sharpe=5.0, n=1, skew=0, kurt=3) == 0.5


def test_psr_degenerate_variance_returns_half():
    """Values chosen so 1 - γ3·SR + (γ4-1)/4·SR² < 0."""
    # 1 - 1.5*2 + (1-1)/4 * 4 = 1 - 3 + 0 = -2
    p = psr(sharpe=2.0, n=100, skew=1.5, kurt=1, benchmark_sr=0.0)
    assert p == 0.5


def test_psr_accepts_float_n_for_effective_sample_size():
    """Uniqueness-weighted effective_n (float) must be a valid n input."""
    p = psr(sharpe=0.5, n=50.5, skew=0.0, kurt=3.0, benchmark_sr=0.0)
    assert 0.0 <= p <= 1.0


def test_psr_effective_n_lower_than_raw_n_reduces_confidence():
    """Reducing effective sample size (as uniqueness deflation does) must
    move PSR toward 0.5 (indifference), never away."""
    raw = psr(sharpe=0.3, n=60, skew=0.0, kurt=3, benchmark_sr=0.0)
    eff = psr(sharpe=0.3, n=30.0, skew=0.0, kurt=3, benchmark_sr=0.0)
    # Positive edge → both above 0.5, effective (smaller n) closer to 0.5
    assert raw > eff > 0.5


def test_psr_below_two_effective_returns_indifference():
    """Effective n < 2 (e.g. after severe uniqueness deflation) is honest 0.5."""
    assert psr(sharpe=0.5, n=1.5, skew=0.0, kurt=3.0) == 0.5


# --- hhi -------------------------------------------------------------------


def test_hhi_uniform_positive_returns_zero():
    h = hhi([0.1, 0.1, 0.1, 0.1, -0.05], side="positive")
    assert h == pytest.approx(0.0, abs=1e-9)


def test_hhi_single_dominant_positive_approaches_one():
    h = hhi([10.0, 0.001, 0.001, 0.001, -0.5], side="positive")
    assert h > 0.9


def test_hhi_negative_side_symmetric():
    h = hhi([0.1, -0.5, -0.5, -0.5], side="negative")
    assert h == pytest.approx(0.0, abs=1e-9)


def test_hhi_tiny_side_returns_none():
    assert hhi([0.5], side="positive") is None
    assert hhi([-0.5, -0.3], side="positive") is None


def test_hhi_rejects_unknown_side():
    with pytest.raises(ValueError):
        hhi([0.1, -0.1], side="sideways")


# --- average_uniqueness ---------------------------------------------------


def test_average_uniqueness_disjoint_is_one():
    ivs = [(0, 1), (2, 3), (4, 5)]
    grid = [0, 1, 2, 3, 4, 5]
    assert average_uniqueness(ivs, grid=grid) == pytest.approx(1.0, abs=1e-9)


def test_average_uniqueness_identical_pair_is_half():
    ivs = [(0, 5), (0, 5)]
    grid = [0, 1, 2, 3, 4, 5]
    assert average_uniqueness(ivs, grid=grid) == pytest.approx(0.5, abs=1e-9)


def test_average_uniqueness_empty_returns_one():
    assert average_uniqueness([], grid=[0, 1, 2]) == 1.0


def test_average_uniqueness_partial_overlap_between_half_and_one():
    """Two intervals overlapping halfway — uniqueness ≈ 0.75."""
    ivs = [(0, 4), (2, 6)]
    grid = [0, 1, 2, 3, 4, 5, 6]
    u = average_uniqueness(ivs, grid=grid)
    assert 0.5 < u < 1.0
