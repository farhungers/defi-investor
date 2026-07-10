"""Tests for the from-scratch purged K-Fold CV."""
from __future__ import annotations

import pandas as pd
import pytest

from defi_investor.backtest.cv import (
    Fold,
    PurgedKFold,
    apply_embargo,
    drop_overlapping,
)


def _mk(pairs):
    """Build a sorted pd.Series from [(anchor, barrier_hit), ...]."""
    idx = pd.to_datetime([a for a, _ in pairs])
    val = pd.to_datetime([b for _, b in pairs])
    return pd.Series(val, index=idx).sort_index()


# --- drop_overlapping ------------------------------------------------------


def test_drop_overlapping_removes_label_starting_inside_window():
    intervals = _mk([
        ("2026-01-01", "2026-01-02"),
        ("2026-01-05", "2026-01-06"),   # anchor inside test [01-04, 01-07]
        ("2026-01-10", "2026-01-11"),
    ])
    survivors = drop_overlapping(
        intervals, (pd.Timestamp("2026-01-04"), pd.Timestamp("2026-01-07"))
    )
    kept = [str(t.date()) for t in survivors.index]
    assert kept == ["2026-01-01", "2026-01-10"]


def test_drop_overlapping_removes_label_ending_inside_window():
    intervals = _mk([
        ("2026-01-01", "2026-01-05"),   # barrier inside test [01-04, 01-07]
        ("2026-01-10", "2026-01-11"),
    ])
    survivors = drop_overlapping(
        intervals, (pd.Timestamp("2026-01-04"), pd.Timestamp("2026-01-07"))
    )
    kept = [str(t.date()) for t in survivors.index]
    assert kept == ["2026-01-10"]


def test_drop_overlapping_removes_label_enveloping_window():
    intervals = _mk([
        ("2026-01-01", "2026-01-31"),   # envelops test [01-10, 01-15]
        ("2026-02-01", "2026-02-05"),
    ])
    survivors = drop_overlapping(
        intervals, (pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-15"))
    )
    kept = [str(t.date()) for t in survivors.index]
    assert kept == ["2026-02-01"]


def test_drop_overlapping_keeps_disjoint():
    intervals = _mk([
        ("2026-01-01", "2026-01-02"),
        ("2026-01-20", "2026-01-21"),
    ])
    survivors = drop_overlapping(
        intervals, (pd.Timestamp("2026-01-10"), pd.Timestamp("2026-01-15"))
    )
    assert len(survivors) == 2


# --- apply_embargo ---------------------------------------------------------


def test_apply_embargo_drops_anchor_in_tail():
    intervals = _mk([
        ("2026-01-01", "2026-01-02"),
        ("2026-01-08", "2026-01-09"),   # anchor just after window_end
        ("2026-06-01", "2026-06-02"),
    ])
    survivors = apply_embargo(intervals, pd.Timestamp("2026-01-07"), fraction=0.01)
    kept = [str(t.date()) for t in survivors.index]
    assert "2026-01-08" not in kept
    assert "2026-06-01" in kept


def test_apply_embargo_zero_fraction_is_noop():
    intervals = _mk([("2026-01-01", "2026-01-02"), ("2026-01-08", "2026-01-09")])
    survivors = apply_embargo(intervals, pd.Timestamp("2026-01-07"), fraction=0.0)
    assert len(survivors) == 2


# --- PurgedKFold -----------------------------------------------------------


def _monthly_intervals(months: int) -> pd.Series:
    return _mk([
        (f"2026-{m:02d}-01", f"2026-{m:02d}-02") for m in range(1, months + 1)
    ])


def test_purgedkfold_rejects_bad_input():
    with pytest.raises(TypeError):
        PurgedKFold(intervals=[1, 2, 3], n_splits=3)
    with pytest.raises(ValueError):
        PurgedKFold(intervals=_monthly_intervals(3), n_splits=1)


def test_purgedkfold_yields_expected_fold_count_and_covers_all():
    cv = PurgedKFold(intervals=_monthly_intervals(9), n_splits=3, embargo_fraction=0.0)
    folds = list(cv.iter_folds())
    assert len(folds) == 3
    covered = []
    for f in folds:
        covered.extend(f.test)
    assert sorted(covered) == list(range(9))


def test_purgedkfold_train_disjoint_from_test():
    cv = PurgedKFold(intervals=_monthly_intervals(9), n_splits=3, embargo_fraction=0.0)
    for f in cv.iter_folds():
        assert not (set(f.train) & set(f.test))


def test_purgedkfold_folds_have_expected_size_distribution():
    """10 rows / 3 folds → sizes 4, 3, 3."""
    cv = PurgedKFold(intervals=_monthly_intervals(10), n_splits=3, embargo_fraction=0.0)
    sizes = [len(f.test) for f in cv.iter_folds()]
    assert sorted(sizes) == [3, 3, 4]


def test_purgedkfold_embargo_shrinks_training_sets():
    a = PurgedKFold(intervals=_monthly_intervals(9), n_splits=3, embargo_fraction=0.0)
    b = PurgedKFold(intervals=_monthly_intervals(9), n_splits=3, embargo_fraction=0.20)
    assert sum(b.train_sizes()) <= sum(a.train_sizes())


def test_purgedkfold_reports_purge_and_embargo_counts():
    """A label whose barrier stretches into a later fold gets purged."""
    intervals = _mk([
        ("2026-01-01", "2026-01-25"),   # spans into fold 1 and 2
        ("2026-01-08", "2026-01-09"),
        ("2026-01-10", "2026-01-11"),
        ("2026-01-12", "2026-01-13"),
        ("2026-01-14", "2026-01-15"),
        ("2026-01-16", "2026-01-17"),
    ])
    cv = PurgedKFold(intervals=intervals, n_splits=3, embargo_fraction=0.05)
    folds = list(cv.iter_folds())
    assert all(isinstance(f, Fold) for f in folds)
    # Fold 1 (indices 2,3) has test window inside the first label's span
    # so the first label must be purged from its training set.
    assert any(f.n_purged > 0 for f in folds)


def test_purgedkfold_unsorted_input_is_sorted_internally():
    idx = pd.to_datetime(["2026-03-01", "2026-01-01", "2026-02-01"])
    val = pd.to_datetime(["2026-03-02", "2026-01-02", "2026-02-02"])
    intervals = pd.Series(val, index=idx)  # NOT sorted
    cv = PurgedKFold(intervals=intervals, n_splits=3, embargo_fraction=0.0)
    folds = list(cv.iter_folds())
    # After sort the test-fold order should match the sorted index
    assert folds[0].test_anchor_start == pd.Timestamp("2026-01-01")
    assert folds[-1].test_anchor_start == pd.Timestamp("2026-03-01")
