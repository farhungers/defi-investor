"""End-to-end integration test for the A3 pipeline.

Wires together the modules that a real Phase 3e deploy will use, without
touching Supabase or Bitget/Binance live APIs. The chain under test:

    L2 snapshots (fabricated)
        -> orderbook.features.compute_depth_asymmetry_5min
        -> {asymmetry, ws_gap_max_s, coverage_pre}
        -> label decision at theta_asym=0.5 (per HYPOTHESIS_A3)

If any of the primitives drift in a way that would break the labeler,
this test catches it. Not a Supabase test — the DB roundtrip is covered
by unit tests on storage.BatchedL2Writer.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import pytest

from defi_investor.orderbook import L2Snapshot
from defi_investor.orderbook.features import compute_depth_asymmetry_5min


ANCHOR = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
THETA_ASYM = 0.5   # per HYPOTHESIS_A3 §Labeler spec, pre-committed


def _mk_snapshot(
    *,
    seconds_before_anchor: float,
    ask_size: float,
    bid_size: float,
    venue: str = "bitget",
    inst_id: str = "BTCUSDT",
) -> L2Snapshot:
    ts = ANCHOR - timedelta(seconds=seconds_before_anchor)
    ts_ms = int(ts.timestamp() * 1000)
    return L2Snapshot(
        venue=venue,
        inst_id=inst_id,
        received_at=ts.isoformat(),
        exchange_ts_ms=ts_ms,
        bids=[(100.0 - 0.01 * i, bid_size) for i in range(5)],
        asks=[(100.0 + 0.01 * i, ask_size) for i in range(5)],
    )


def _label_from_asymmetry(asym: float | None) -> int | None:
    """Mirrors backfill_labels_a3._label_from_asymmetry (post-fix).

    +1 if ask-side contraction (=> asymmetry <= -theta_asym)
    -1 if bid-side contraction (=> asymmetry >= +theta_asym)
     0 otherwise
    """
    if asym is None:
        return None
    if asym <= -THETA_ASYM:
        return +1
    if asym >= THETA_ASYM:
        return -1
    return 0


def _dense_stream(
    *,
    ask_size_pre: float, ask_size_pre_pre: float,
    bid_size_pre: float, bid_size_pre_pre: float,
    cadence_seconds: float = 1.0,
) -> list[L2Snapshot]:
    """1 snapshot per `cadence_seconds` covering the 10-min pre + pre-pre window."""
    snaps: list[L2Snapshot] = []
    t = 0.0
    while t < 600.0:  # 10 minutes
        if t < 300.0:  # in pre window (< 5 min before anchor)
            snaps.append(_mk_snapshot(
                seconds_before_anchor=t,
                ask_size=ask_size_pre, bid_size=bid_size_pre,
            ))
        else:  # pre_pre window (5..10 min before)
            snaps.append(_mk_snapshot(
                seconds_before_anchor=t,
                ask_size=ask_size_pre_pre, bid_size=bid_size_pre_pre,
            ))
        t += cadence_seconds
    return snaps


# --- End-to-end scenarios per HYPOTHESIS_A3 spec -----------------------------

def test_pipeline_symmetric_flow_labels_zero():
    snaps = _dense_stream(
        ask_size_pre=10.0, ask_size_pre_pre=10.0,
        bid_size_pre=10.0, bid_size_pre_pre=10.0,
    )
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert f.asymmetry == pytest.approx(0.0, abs=1e-10)
    assert _label_from_asymmetry(f.asymmetry) == 0


def test_pipeline_strong_ask_contraction_labels_plus_one():
    """Per HYPOTHESIS_A3: ask contraction should yield label +1.

    Ask depth in pre window is 30% of pre_pre; bids unchanged.
    Formula: (log(ask_pre) - log(ask_pre_pre)) - (log(bid_pre) - log(bid_pre_pre))
           = log(0.3) - 0 ~= -1.204

    Ask contraction => NEGATIVE asymmetry => label +1 per the corrected
    _label_from_asymmetry mapping (fixed 2026-07-28 after this test
    caught an inverted-sign bug in backfill_labels_a3).
    """
    snaps = _dense_stream(
        ask_size_pre=3.0, ask_size_pre_pre=10.0,
        bid_size_pre=10.0, bid_size_pre_pre=10.0,
    )
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    # 1% tolerance absorbs the boundary snapshot at t=300s landing in the
    # pre-bucket instead of pre_pre-bucket (window-boundary inclusivity).
    assert f.asymmetry == pytest.approx(math.log(0.3), rel=0.01)
    assert _label_from_asymmetry(f.asymmetry) == +1


def test_pipeline_strong_bid_contraction_labels_minus_one():
    """Per HYPOTHESIS_A3: bid contraction should yield label -1."""
    snaps = _dense_stream(
        ask_size_pre=10.0, ask_size_pre_pre=10.0,
        bid_size_pre=3.0, bid_size_pre_pre=10.0,
    )
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    # bid contraction => POSITIVE asymmetry (~ +1.204)
    assert f.asymmetry == pytest.approx(-math.log(0.3), rel=0.01)
    assert _label_from_asymmetry(f.asymmetry) == -1


def test_pipeline_below_theta_labels_zero():
    # 5% ask contraction — well below theta_asym=0.5.
    snaps = _dense_stream(
        ask_size_pre=9.5, ask_size_pre_pre=10.0,
        bid_size_pre=10.0, bid_size_pre_pre=10.0,
    )
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert abs(f.asymmetry) < THETA_ASYM
    assert _label_from_asymmetry(f.asymmetry) == 0


def test_pipeline_ws_gap_exclusion_signal():
    # Only two snapshots, 200 seconds apart in the combined window.
    snaps = [
        _mk_snapshot(seconds_before_anchor=400.0, ask_size=10.0, bid_size=10.0),
        _mk_snapshot(seconds_before_anchor=100.0, ask_size=10.0, bid_size=10.0),
    ]
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    # Gap between them is 300s => triggers the >= 60s exclusion rule
    assert f.ws_gap_max_s == pytest.approx(300.0, abs=1)
    # backfill_labels_a3 excludes with reason ws_gap_over_60s_in_pre_window
    # when this fires. The label decision is not made in that path.


def test_pipeline_no_snapshots_returns_no_label():
    f = compute_depth_asymmetry_5min([], ANCHOR)
    assert f.asymmetry is None
    assert _label_from_asymmetry(f.asymmetry) is None


def test_pipeline_only_pre_window_no_baseline_no_label():
    # Snapshots only in the pre window — can't compute the log-ratio because
    # pre_pre depths are undefined.
    snaps = [
        _mk_snapshot(seconds_before_anchor=t, ask_size=10.0, bid_size=10.0)
        for t in range(0, 300)
    ]
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert f.asymmetry is None
    assert _label_from_asymmetry(f.asymmetry) is None


def test_pipeline_coverage_meets_gate():
    """coverage_pre >= 70% is the A3 gate criterion #4. Full 1s cadence
    yields near-100% coverage."""
    snaps = _dense_stream(
        ask_size_pre=10.0, ask_size_pre_pre=10.0,
        bid_size_pre=10.0, bid_size_pre_pre=10.0,
        cadence_seconds=1.0,
    )
    f = compute_depth_asymmetry_5min(snaps, ANCHOR)
    assert f.coverage_pre >= 0.99
