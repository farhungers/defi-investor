"""Tests for orderbook.features.compute_depth_asymmetry_5min (HYPOTHESIS_A3)."""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable

import pytest

from defi_investor.orderbook.features import (
    DepthAsymmetryResult,
    compute_depth_asymmetry_5min,
)


@dataclass(frozen=True)
class _Snap:
    exchange_ts_ms: int
    bids: list[tuple[float, float]]
    asks: list[tuple[float, float]]


ANCHOR = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)


def _mk_snapshots(
    times_seconds_before_anchor: list[float],
    bid_size: float = 10.0,
    ask_size: float = 10.0,
    depth_ask_multiplier_pre: float = 1.0,
    depth_bid_multiplier_pre: float = 1.0,
) -> list[_Snap]:
    """Build a list of _Snap objects with 5-level books.

    `depth_ask_multiplier_pre` and `depth_bid_multiplier_pre` scale the
    top-5 depth on the pre (<= 5min) side vs pre_pre (5-10min).
    """
    out = []
    for sec_before in times_seconds_before_anchor:
        ts = ANCHOR - timedelta(seconds=sec_before)
        ts_ms = int(ts.timestamp() * 1000)
        in_pre = sec_before <= 300  # <=5min
        ask_mult = depth_ask_multiplier_pre if in_pre else 1.0
        bid_mult = depth_bid_multiplier_pre if in_pre else 1.0
        # 5 levels each with the given size×mult
        bids = [(100.0 - 0.01 * i, bid_size * bid_mult) for i in range(5)]
        asks = [(100.0 + 0.01 * i, ask_size * ask_mult) for i in range(5)]
        out.append(_Snap(exchange_ts_ms=ts_ms, bids=bids, asks=asks))
    return out


def test_symmetric_no_change_asymmetry_zero():
    # Snapshots every 1s in both pre-pre and pre. Depths unchanged.
    times = [i for i in range(0, 600)]  # 600 snapshots over 10 min
    snaps = _mk_snapshots(times, ask_size=10.0, bid_size=10.0)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert r.asymmetry == pytest.approx(0.0, abs=1e-10)
    assert r.n_snapshots_pre > 200
    assert r.n_snapshots_pre_pre > 200


def test_ask_contraction_gives_negative_asymmetry():
    # Pre-window ask depth halves; bid unchanged.
    # Spec: (log(ask_pre) - log(ask_pre_pre)) - (log(bid_pre) - log(bid_pre_pre))
    # = log(0.5) - log(1.0) - (0 - 0) = log(0.5) ~ -0.693
    times = list(range(0, 600))
    snaps = _mk_snapshots(times, depth_ask_multiplier_pre=0.5, depth_bid_multiplier_pre=1.0)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert r.asymmetry == pytest.approx(math.log(0.5), rel=1e-6)


def test_bid_contraction_gives_positive_asymmetry():
    # Pre-window bid depth halves; ask unchanged. Sign should be POSITIVE.
    times = list(range(0, 600))
    snaps = _mk_snapshots(times, depth_ask_multiplier_pre=1.0, depth_bid_multiplier_pre=0.5)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    # 0 - log(0.5) = +0.693
    assert r.asymmetry == pytest.approx(-math.log(0.5), rel=1e-6)


def test_empty_snapshots_returns_all_none():
    r = compute_depth_asymmetry_5min([], ANCHOR)
    assert r.asymmetry is None
    assert r.n_snapshots_pre == 0
    assert r.n_snapshots_pre_pre == 0
    assert r.coverage_pre == 0.0


def test_snapshots_all_outside_window_returns_none():
    # Snapshots 15 minutes before — outside pre_pre range
    times = [900 + i for i in range(60)]
    snaps = _mk_snapshots(times)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert r.n_snapshots_pre == 0
    assert r.n_snapshots_pre_pre == 0
    assert r.asymmetry is None


def test_ws_gap_max_s_detects_long_gap():
    # Snapshot at 400s (in pre_pre), then next at 100s (in pre) — gap 300s
    snaps = _mk_snapshots([400, 100])
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert r.ws_gap_max_s == pytest.approx(300.0, abs=1)


def test_ws_gap_max_s_none_with_zero_or_one_snapshot():
    r0 = compute_depth_asymmetry_5min([], ANCHOR)
    assert r0.ws_gap_max_s is None
    r1 = compute_depth_asymmetry_5min(_mk_snapshots([100]), ANCHOR)
    assert r1.ws_gap_max_s is None


def test_coverage_pre_full_dense_stream():
    # 1-second snapshots for the full 5-minute pre window
    times = list(range(0, 300))
    snaps = _mk_snapshots(times)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert r.coverage_pre == pytest.approx(1.0, abs=1e-6)


def test_coverage_pre_half_missing():
    # Snapshots only in first half of pre window (150-300s before anchor)
    times = list(range(150, 300))
    snaps = _mk_snapshots(times)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert 0.3 < r.coverage_pre < 0.6


def test_only_pre_window_populated_returns_none_asymmetry():
    # No pre_pre data → log ratio undefined → asymmetry None
    times = list(range(0, 300))  # only pre window
    snaps = _mk_snapshots(times)
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert r.asymmetry is None
    assert r.n_snapshots_pre > 0
    assert r.n_snapshots_pre_pre == 0


def test_short_book_handled_without_error():
    # Only 3 levels each side; sum_top5 handles the short book.
    ts_ms = int((ANCHOR - timedelta(seconds=60)).timestamp() * 1000)
    snap = _Snap(
        exchange_ts_ms=ts_ms,
        bids=[(100.0, 5.0), (99.99, 5.0), (99.98, 5.0)],
        asks=[(100.01, 5.0), (100.02, 5.0), (100.03, 5.0)],
    )
    r = compute_depth_asymmetry_5min([snap], ANCHOR)
    # depth_ask_pre = 15.0; no pre_pre → asymmetry None
    assert r.depth_ask_pre == pytest.approx(15.0)
    assert r.depth_bid_pre == pytest.approx(15.0)
    assert r.asymmetry is None


def test_zero_depth_produces_none_asymmetry_not_crash():
    # log(0) would be undefined; _safe_log_ratio returns None gracefully.
    times = [400.0, 100.0]  # one in each window
    snaps = _mk_snapshots(times)
    # Rewrite second snapshot's asks to zero-size
    snaps = list(snaps)
    original = snaps[1]
    snaps[1] = _Snap(
        exchange_ts_ms=original.exchange_ts_ms,
        bids=original.bids,
        asks=[(p, 0.0) for p, _ in original.asks],
    )
    r = compute_depth_asymmetry_5min(snaps, ANCHOR)
    # Averaged pre depth for asks is 0 → log undefined → asymmetry None
    assert r.asymmetry is None
