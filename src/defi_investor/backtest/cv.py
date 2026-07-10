"""Purged K-Fold cross-validation for defi-investor labels.

Built from de Prado's *Advances in Financial Machine Learning* Ch 7. The
math is standard; the code is defi-investor-native and stands alone.

## Why purging is required for Earn-event labels

Each Earn-event label spans a real time interval — from the anchor
timestamp (usually `sold_out_first_seen_at`) to whichever barrier hits
first (`T1_UP`, `T1_DOWN`, or `T2`). Two events on the same coin, or
two events on different coins whose intervals happen to overlap, are
statistically dependent. Standard K-Fold CV treats them as independent
and produces optimistic out-of-sample scores.

Two countermeasures, both required, both implemented here:

1. **Purge**: drop training labels whose interval overlaps the test-fold
   interval. Prevents label leakage backward and forward.
2. **Embargo**: drop training labels whose anchor falls in a short window
   AFTER the test-fold interval. Prevents forward-only serial-correlation
   leakage that purging alone misses.

The default embargo is 1% of the corpus's total time span — the number
that CHARTER §5 and METHOD §3.2 both fix.

## Data shape

The primitives take a pandas `Series`:

    index = anchor_ts (label start)
    value = barrier_hit_ts (label end)

sorted ascending by anchor_ts. This matches how the Phase 2 labeler
writes to `earn_event_labels` and lets us reuse pandas' native
timestamp comparisons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterator

import pandas as pd


# ---------- data classes ---------------------------------------------------


@dataclass(frozen=True)
class Fold:
    """One resolved train/test split from a PurgedKFold run.

    Positions are integer offsets into the input Series so downstream code
    can slice a feature matrix with `.iloc[fold.train]`.
    """
    index: int
    train: list[int]
    test: list[int]
    test_anchor_start: pd.Timestamp
    test_barrier_end: pd.Timestamp
    n_purged: int
    n_embargoed: int


# ---------- interval overlap primitive -------------------------------------


def _intervals_overlap(a_start: pd.Timestamp, a_end: pd.Timestamp,
                       b_start: pd.Timestamp, b_end: pd.Timestamp) -> bool:
    """Half-open interval overlap check.

    Two closed intervals [a_start, a_end] and [b_start, b_end] overlap iff
    a_start <= b_end AND b_start <= a_end. Cleaner than de Prado's three
    conditional cases; same result.
    """
    return (a_start <= b_end) and (b_start <= a_end)


def drop_overlapping(intervals: pd.Series,
                     window: tuple[pd.Timestamp, pd.Timestamp]) -> pd.Series:
    """Return the subset of `intervals` whose label span does NOT overlap
    the given test `window`.

    Args:
        intervals: pd.Series indexed by anchor_ts, valued by barrier_hit_ts.
        window: (window_start, window_end) closed interval.

    Returns:
        A pd.Series subset containing only the labels safe to train on.
    """
    w_start, w_end = window
    mask = intervals.index.to_series().combine(
        intervals,
        lambda a, b: not _intervals_overlap(a, b, w_start, w_end),
    )
    return intervals[mask.values]


def apply_embargo(intervals: pd.Series,
                  window_end: pd.Timestamp,
                  fraction: float = 0.01) -> pd.Series:
    """Drop labels whose anchor lands in the embargo tail after `window_end`.

    The embargo length is `fraction * total_corpus_span` seconds, computed
    from the FULL corpus (not the remaining survivors) so the embargo is
    fold-independent.

    Args:
        intervals: pd.Series indexed by anchor_ts.
        window_end: End of the test interval.
        fraction: Embargo length as a fraction of total corpus span
            (default 0.01 = 1%, per METHOD §3.2 and CHARTER §5).

    Returns:
        A pd.Series with post-window embargo labels removed.
    """
    if intervals.empty or fraction <= 0:
        return intervals
    corpus_span_s = (intervals.index.max() - intervals.index.min()).total_seconds()
    embargo_s = fraction * corpus_span_s
    embargo_end = window_end + pd.Timedelta(seconds=embargo_s)
    # Keep everything that does NOT sit in (window_end, embargo_end]
    in_embargo = (intervals.index > window_end) & (intervals.index <= embargo_end)
    return intervals[~in_embargo]


# ---------- iterator -------------------------------------------------------


class PurgedKFold:
    """K-Fold split for time-interval labels with purge + embargo.

    Test folds are contiguous slices of the sorted label index. Training
    positions are the complement minus any label whose interval overlaps
    the test window (purge) or whose anchor lands in the embargo tail.

    Args:
        intervals: pd.Series indexed by anchor_ts, valued by barrier_hit_ts.
        n_splits: number of contiguous test folds. Must be >= 2. METHOD
            §3.3 fixes n_splits = 3 at n = 30 and n_splits = 5 at n = 100.
        embargo_fraction: post-fold exclusion tail as a fraction of the
            corpus time span. Default 0.01.

    Example:
        >>> intervals = pd.Series(barrier_hit_ts, index=anchor_ts).sort_index()
        >>> cv = PurgedKFold(intervals=intervals, n_splits=3)
        >>> for fold in cv.iter_folds():
        ...     X_tr, y_tr = X.iloc[fold.train], y.iloc[fold.train]
        ...     X_te, y_te = X.iloc[fold.test], y.iloc[fold.test]
        ...     ...
    """

    def __init__(self, *, intervals: pd.Series, n_splits: int = 3,
                 embargo_fraction: float = 0.01):
        if not isinstance(intervals, pd.Series):
            raise TypeError("intervals must be a pd.Series")
        if n_splits < 2:
            raise ValueError("n_splits must be >= 2")
        if not intervals.index.is_monotonic_increasing:
            intervals = intervals.sort_index()
        self.intervals = intervals
        self.n_splits = n_splits
        self.embargo_fraction = embargo_fraction

    def _fold_bounds(self) -> list[tuple[int, int]]:
        """Compute (start, end) integer bounds for each contiguous test fold.

        Distributes the remainder evenly across the first folds so no fold
        differs from another by more than one row.
        """
        n = len(self.intervals)
        base, extra = divmod(n, self.n_splits)
        bounds: list[tuple[int, int]] = []
        cursor = 0
        for k in range(self.n_splits):
            size = base + (1 if k < extra else 0)
            bounds.append((cursor, cursor + size))
            cursor += size
        return bounds

    def iter_folds(self) -> Iterator[Fold]:
        """Yield `Fold` records with train and test integer positions."""
        for k, (a, b) in enumerate(self._fold_bounds()):
            if a == b:
                continue
            test_positions = list(range(a, b))
            test_start = self.intervals.index[a]
            test_end = self.intervals.iloc[b - 1]

            purged = drop_overlapping(self.intervals, (test_start, test_end))
            n_purged = len(self.intervals) - len(test_positions) - len(purged)

            embargoed = apply_embargo(purged, test_end, self.embargo_fraction)
            n_embargoed = len(purged) - len(embargoed)

            # Map surviving anchor timestamps back to integer positions;
            # exclude anything that would land inside the test window.
            all_positions = self.intervals.index.get_indexer(embargoed.index)
            train_positions = [
                int(p) for p in all_positions
                if p >= 0 and (p < a or p >= b)
            ]
            yield Fold(
                index=k,
                train=train_positions,
                test=test_positions,
                test_anchor_start=test_start,
                test_barrier_end=test_end,
                n_purged=n_purged,
                n_embargoed=n_embargoed,
            )

    def train_sizes(self) -> list[int]:
        """Convenience: sizes of each fold's training set post-purge/embargo.

        Reporting this alongside raw n keeps us honest about how much the
        purge is eating — a common blind spot at low n.
        """
        return [len(f.train) for f in self.iter_folds()]
