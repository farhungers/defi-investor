"""Order-book feature extraction for HYPOTHESIS_A3.

Pure functions over `Iterable[L2Snapshot]`. Callers supply already-fetched
snapshots (from storage or in-memory buffer); this module never fetches
or connects.

Pre-registered spec (docs/preregistrations/HYPOTHESIS_A3.md §Labeler spec):
    depth_asymmetry_5min =
        (log(depth_ask_top5_pre) - log(depth_ask_top5_pre_pre))
      - (log(depth_bid_top5_pre) - log(depth_bid_top5_pre_pre))

    where:
      pre_pre window = [anchor - 10min, anchor - 5min]
      pre     window = [anchor -  5min,  anchor]
      depth_ask_top5(t) = sum(size for price, size in snap.asks[:5])
      window average = arithmetic mean of top5 depth across all snapshots
                       whose exchange timestamp falls in the window

Exclusion signals (also computed here so the labeler can decide):
    ws_gap_max_s:      max seconds between consecutive snapshots in the
                       combined pre+pre_pre window. >= 60 triggers
                       exclusion per spec.
    coverage_pre:      fraction of the 5-minute pre window covered by
                       at least one snapshot per 5-second slice
                       (rough denseness metric).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional


@dataclass(frozen=True)
class DepthAsymmetryResult:
    asymmetry: Optional[float]           # None if either window is empty
    depth_ask_pre: Optional[float]
    depth_ask_pre_pre: Optional[float]
    depth_bid_pre: Optional[float]
    depth_bid_pre_pre: Optional[float]
    n_snapshots_pre: int
    n_snapshots_pre_pre: int
    ws_gap_max_s: Optional[float]        # None if fewer than 2 snapshots in combined window
    coverage_pre: float                  # 0.0..1.0; naive dense-coverage estimate


def _sum_top5(levels) -> float:
    """Sum sizes across up to top-5 levels. Handles short books."""
    total = 0.0
    for _p, s in list(levels)[:5]:
        total += float(s)
    return total


def _average(values: list[float]) -> Optional[float]:
    if not values:
        return None
    return sum(values) / len(values)


def _safe_log_ratio(a: Optional[float], b: Optional[float]) -> Optional[float]:
    if a is None or b is None or a <= 0 or b <= 0:
        return None
    return math.log(a) - math.log(b)


def compute_depth_asymmetry_5min(
    snapshots: Iterable,
    anchor: datetime,
    *,
    window_minutes: int = 5,
    pre_pre_window_minutes: int = 5,
    coverage_slice_seconds: int = 5,
) -> DepthAsymmetryResult:
    """Compute the pre-registered A3 depth_asymmetry_5min feature.

    `snapshots` is any iterable of objects exposing:
        exchange_ts_ms (int, epoch ms)
        bids  (Iterable[(price, size)])
        asks  (Iterable[(price, size)])
    `anchor` is the sold_out_first_seen_at datetime (UTC).

    Default windows follow spec verbatim: 5-min pre and 5-min pre-pre.
    """
    if anchor.tzinfo is None:
        anchor = anchor.replace(tzinfo=timezone.utc)

    pre_end = anchor
    pre_start = anchor - timedelta(minutes=window_minutes)
    pre_pre_end = pre_start
    pre_pre_start = pre_pre_end - timedelta(minutes=pre_pre_window_minutes)

    ask_pre: list[float] = []
    bid_pre: list[float] = []
    ask_pre_pre: list[float] = []
    bid_pre_pre: list[float] = []

    all_ts_ms_in_combined_window: list[int] = []

    for snap in snapshots:
        ts_ms = int(snap.exchange_ts_ms)
        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        if pre_pre_start <= ts < pre_pre_end:
            ask_pre_pre.append(_sum_top5(snap.asks))
            bid_pre_pre.append(_sum_top5(snap.bids))
            all_ts_ms_in_combined_window.append(ts_ms)
        elif pre_start <= ts <= pre_end:
            ask_pre.append(_sum_top5(snap.asks))
            bid_pre.append(_sum_top5(snap.bids))
            all_ts_ms_in_combined_window.append(ts_ms)

    depth_ask_pre = _average(ask_pre)
    depth_ask_pre_pre = _average(ask_pre_pre)
    depth_bid_pre = _average(bid_pre)
    depth_bid_pre_pre = _average(bid_pre_pre)

    ask_component = _safe_log_ratio(depth_ask_pre, depth_ask_pre_pre)
    bid_component = _safe_log_ratio(depth_bid_pre, depth_bid_pre_pre)
    asymmetry = (
        ask_component - bid_component
        if ask_component is not None and bid_component is not None
        else None
    )

    # ws_gap_max_s: largest gap between consecutive snapshots (sorted).
    all_ts_ms_in_combined_window.sort()
    ws_gap_max_s: Optional[float] = None
    if len(all_ts_ms_in_combined_window) >= 2:
        gaps = [
            (all_ts_ms_in_combined_window[i + 1] - all_ts_ms_in_combined_window[i]) / 1000.0
            for i in range(len(all_ts_ms_in_combined_window) - 1)
        ]
        ws_gap_max_s = max(gaps) if gaps else None

    # Coverage of the pre window: how many 5-second slices had at least
    # one snapshot? 5 min = 300 s; 60 slices at 5s each.
    n_slices = int((window_minutes * 60) / coverage_slice_seconds)
    slice_ms = coverage_slice_seconds * 1000
    pre_start_ms = int(pre_start.timestamp() * 1000)
    covered_slices = set()
    for snap in snapshots:
        ts_ms = int(snap.exchange_ts_ms)
        ts = datetime.fromtimestamp(ts_ms / 1000.0, tz=timezone.utc)
        if not (pre_start <= ts <= pre_end):
            continue
        slice_idx = (ts_ms - pre_start_ms) // slice_ms
        if 0 <= slice_idx < n_slices:
            covered_slices.add(slice_idx)
    coverage_pre = len(covered_slices) / n_slices if n_slices else 0.0

    return DepthAsymmetryResult(
        asymmetry=asymmetry,
        depth_ask_pre=depth_ask_pre,
        depth_ask_pre_pre=depth_ask_pre_pre,
        depth_bid_pre=depth_bid_pre,
        depth_bid_pre_pre=depth_bid_pre_pre,
        n_snapshots_pre=len(ask_pre),
        n_snapshots_pre_pre=len(ask_pre_pre),
        ws_gap_max_s=ws_gap_max_s,
        coverage_pre=coverage_pre,
    )
