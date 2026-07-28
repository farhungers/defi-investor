"""Tests for the v0.3.0 triple-barrier labeler (HYPOTHESIS_A2b).

Uses injected DataFrames so tests are fully offline; live-fetch path is
smoke-tested separately when backfill is wired up.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from defi_investor.labelers.triple_barrier_v030 import (
    DEFAULT_K_LOWER,
    DEFAULT_K_UPPER,
    HORIZONS_HOURS,
    LABELER_VERSION,
    label_event,
)
from defi_investor.models import EarnEvent


ANCHOR_ISO = "2026-06-15T12:00:00+00:00"


def _event(coin: str = "TEST", sold_out: bool = True) -> EarnEvent:
    return EarnEvent(
        product_id=f"{coin}_001",
        coin_name=coin,
        second_biz_line="Savings",
        venue="bitget",
        sold_out=sold_out,
        sold_out_first_seen_at=ANCHOR_ISO if sold_out else None,
    )


def _daily_df(n: int = 30, base: float = 100.0, sigma_daily_log: float = 0.02, seed: int = 42):
    """Daily OHLC df ending at `ANCHOR_ISO` date, synthetic log-normal walk."""
    rng = np.random.default_rng(seed)
    end_date = pd.Timestamp(ANCHOR_ISO).normalize()
    idx = pd.date_range(end=end_date, periods=n, freq="1D", tz="UTC")
    closes = [base]
    for _ in range(n - 1):
        closes.append(closes[-1] * math.exp(rng.normal(0.0, sigma_daily_log)))
    return pd.DataFrame(
        {"open": closes, "high": closes, "low": closes, "close": closes},
        index=idx,
    )


def _walk_df(
    n_minutes: int,
    start_price: float,
    price_path: str = "flat",
    tick: float = 0.001,
) -> pd.DataFrame:
    """1m OHLC df starting at anchor, with configurable price behaviour.

    price_path: 'flat' | 'up' | 'down' | 'up_then_down'
    tick: per-bar log return magnitude for non-flat paths
    """
    anchor = pd.Timestamp(ANCHOR_ISO)
    idx = pd.date_range(start=anchor - pd.Timedelta(minutes=1), periods=n_minutes + 1, freq="1min", tz="UTC")

    if price_path == "flat":
        prices = [start_price] * len(idx)
    elif price_path == "up":
        prices = [start_price * math.exp(tick * i) for i in range(len(idx))]
    elif price_path == "down":
        prices = [start_price * math.exp(-tick * i) for i in range(len(idx))]
    elif price_path == "up_then_down":
        half = len(idx) // 2
        up = [start_price * math.exp(tick * i) for i in range(half)]
        peak = up[-1]
        down = [peak * math.exp(-tick * i) for i in range(len(idx) - half)]
        prices = up + down
    else:
        raise ValueError(price_path)

    return pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices},
        index=idx,
    )


def test_non_sold_out_event_returns_empty_dict():
    ev = _event(sold_out=False)
    result = label_event(ev, daily_df=_daily_df(), walk_df=_walk_df(60 * 200, 100.0))
    assert result == {}


def test_returns_one_row_per_horizon():
    ev = _event()
    daily = _daily_df()
    walk = _walk_df(60 * 200, 100.0, price_path="flat")
    result = label_event(ev, daily_df=daily, walk_df=walk)
    assert set(result.keys()) == set(HORIZONS_HOURS)
    for h in HORIZONS_HOURS:
        assert result[h].horizon_hours == h
        assert result[h].labeler_version == LABELER_VERSION
        assert result[h].venue == "bitget"


def test_flat_price_hits_time_barrier():
    # No horizontal barrier crossed → all horizons resolve as TIME.
    ev = _event()
    daily = _daily_df(sigma_daily_log=0.02)
    walk = _walk_df(60 * 200, 100.0, price_path="flat")
    result = label_event(ev, daily_df=daily, walk_df=walk)
    for h in HORIZONS_HOURS:
        row = result[h]
        assert row.label == 0
        assert row.barrier_hit == "TIME"
        assert row.unlabelable_reason is None


def test_strong_uptrend_hits_upper_barrier():
    # Strong monotonic uptrend → upper barrier hit → label = +1
    ev = _event()
    daily = _daily_df(sigma_daily_log=0.005)  # low daily vol → tight barriers
    # Enough 1m bars to cover 168h + pad
    walk = _walk_df(60 * 200, 100.0, price_path="up", tick=0.001)
    result = label_event(ev, daily_df=daily, walk_df=walk)
    # At least the 168h horizon should hit upper (0.001 * 60*168 = 10.08 log units)
    assert result[168].label == +1
    assert result[168].barrier_hit == "UPPER"
    assert result[168].barrier_hit_price >= result[168].upper_barrier


def test_strong_downtrend_hits_lower_barrier():
    ev = _event()
    daily = _daily_df(sigma_daily_log=0.005)
    walk = _walk_df(60 * 200, 100.0, price_path="down", tick=0.001)
    result = label_event(ev, daily_df=daily, walk_df=walk)
    assert result[168].label == -1
    assert result[168].barrier_hit == "LOWER"


def test_insufficient_daily_history_returns_unlabelable():
    ev = _event()
    daily = _daily_df(n=5)  # only 5 days, need 20 for sigma_20d
    walk = _walk_df(60 * 200, 100.0)
    result = label_event(ev, daily_df=daily, walk_df=walk)
    for h in HORIZONS_HOURS:
        assert result[h].unlabelable_reason == "insufficient_history_for_sigma_20d"
        assert result[h].label is None


def test_missing_daily_candles_returns_no_daily_candles():
    ev = _event()
    daily = pd.DataFrame({"close": []}, index=pd.DatetimeIndex([], tz="UTC"))
    walk = _walk_df(60 * 10, 100.0)
    result = label_event(ev, daily_df=daily, walk_df=walk)
    for h in HORIZONS_HOURS:
        assert result[h].unlabelable_reason == "no_daily_candles"


def test_walk_truncated_yields_horizon_not_resolved():
    # Only 12h of 1m bars — 24h/48h/168h all unresolvable.
    ev = _event()
    daily = _daily_df()
    walk = _walk_df(60 * 12, 100.0, price_path="flat")
    result = label_event(ev, daily_df=daily, walk_df=walk)
    for h in HORIZONS_HOURS:
        assert result[h].unlabelable_reason == "horizon_not_yet_resolved"
        assert result[h].sigma_20d is not None  # sigma still computed


def test_barriers_are_multiplicative_around_anchor_close():
    ev = _event()
    # Construct daily df where sigma_20d is a known value.
    # Use 21 daily bars where log returns are exactly 0.01, 0.02 alternating.
    log_returns = [0.01, -0.02] * 10 + [0.01]  # 21 returns → 22 bars, giving 21 log_ret; but rolling(20) needs 20
    prices = [100.0]
    for r in log_returns:
        prices.append(prices[-1] * math.exp(r))
    idx = pd.date_range(end=pd.Timestamp(ANCHOR_ISO).normalize(), periods=len(prices), freq="1D", tz="UTC")
    daily = pd.DataFrame(
        {"open": prices, "high": prices, "low": prices, "close": prices}, index=idx,
    )
    expected_sigma = float(np.std(np.array(log_returns[-20:]), ddof=0))

    walk = _walk_df(60 * 200, 100.0, price_path="flat")
    result = label_event(ev, daily_df=daily, walk_df=walk)
    row = result[24]
    assert row.sigma_20d == pytest.approx(expected_sigma, rel=1e-10)
    assert row.upper_barrier == pytest.approx(row.anchor_close_price * math.exp(DEFAULT_K_UPPER * expected_sigma), rel=1e-10)
    assert row.lower_barrier == pytest.approx(row.anchor_close_price * math.exp(-DEFAULT_K_LOWER * expected_sigma), rel=1e-10)
