"""Tests for family-wise correction helpers."""
from __future__ import annotations

import pytest

from defi_investor.backtest.family_wise import (
    DEFAULT_ALPHA,
    N_REGISTERED,
    bonferroni_alpha,
    holm_bonferroni,
)


def test_bonferroni_alpha_default():
    assert bonferroni_alpha() == pytest.approx(DEFAULT_ALPHA / N_REGISTERED)


def test_bonferroni_alpha_explicit():
    assert bonferroni_alpha(alpha=0.10, n=4) == pytest.approx(0.025)


def test_bonferroni_alpha_zero_n_raises():
    with pytest.raises(ValueError):
        bonferroni_alpha(n=0)


def test_holm_empty():
    assert holm_bonferroni({}) == []


def test_holm_single_hypothesis_below_alpha():
    r = holm_bonferroni({"A": 0.01}, alpha=0.05, n=1)
    assert len(r) == 1
    assert r[0].rejected is True
    assert r[0].corrected_alpha == pytest.approx(0.05)
    assert r[0].corrected_p == pytest.approx(0.01)


def test_holm_smallest_rejected_others_may_follow():
    # All three below alpha/n=0.05/3=0.0167 → all rejected by Holm too.
    pvals = {"A": 0.001, "B": 0.005, "C": 0.010}
    r = holm_bonferroni(pvals, alpha=0.05, n=3)
    assert [x.hypothesis_id for x in r] == ["A", "B", "C"]
    assert all(x.rejected for x in r)
    # Corrected alphas step down: 0.05/3, 0.05/2, 0.05/1
    assert r[0].corrected_alpha == pytest.approx(0.05 / 3)
    assert r[1].corrected_alpha == pytest.approx(0.05 / 2)
    assert r[2].corrected_alpha == pytest.approx(0.05 / 1)


def test_holm_stops_on_first_non_rejection():
    # A=0.005 rejected at 0.0167; B=0.04 NOT rejected at 0.025 → stop.
    # C=0.005 (smaller than B) still would have been rejected in isolation,
    # but Holm's step-down blocks it since we already stopped at rank 2.
    # Note: sort by p ascending; C has to have p > B for the cascade to
    # actually block it. Let's use plain values: A=0.005, B=0.04, C=0.045.
    pvals = {"A": 0.005, "B": 0.04, "C": 0.045}
    r = holm_bonferroni(pvals, alpha=0.05, n=3)
    assert r[0].hypothesis_id == "A"
    assert r[0].rejected is True
    assert r[1].hypothesis_id == "B"
    assert r[1].rejected is False   # 0.04 > 0.05/2 = 0.025
    assert r[2].hypothesis_id == "C"
    assert r[2].rejected is False   # blocked by cascade


def test_holm_n_smaller_than_pvalues_raises():
    with pytest.raises(ValueError):
        holm_bonferroni({"A": 0.01, "B": 0.02}, n=1)


def test_holm_n_larger_than_pvalues_is_allowed():
    # A hypothesis that hasn't been tested yet still counts toward N.
    # We only report on the pvalues supplied; the divisor uses full N.
    r = holm_bonferroni({"A": 0.005}, alpha=0.05, n=4)
    # rank 1 corrected alpha = 0.05 / 4 = 0.0125; 0.005 < 0.0125 → rejected
    assert r[0].rejected is True
    assert r[0].corrected_alpha == pytest.approx(0.05 / 4)


def test_holm_corrected_p_capped_at_one():
    r = holm_bonferroni({"A": 0.9, "B": 0.8, "C": 0.7}, alpha=0.05, n=3)
    for x in r:
        assert 0 <= x.corrected_p <= 1.0
