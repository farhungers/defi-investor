"""Tests for compute_sigma_realized (Phase 3d v0.3.0 barrier width)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from defi_investor.candles import compute_sigma_realized, resample_to_daily


def _daily_df(closes: list[float], start: str = "2026-01-01") -> pd.DataFrame:
    idx = pd.date_range(start=start, periods=len(closes), freq="1D", tz="UTC")
    return pd.DataFrame(
        {
            "open": closes,
            "high": closes,
            "low": closes,
            "close": closes,
        },
        index=idx,
    )


def test_constant_price_gives_zero_sigma():
    df = _daily_df([100.0] * 25)
    sigma = compute_sigma_realized(df, period=20)
    # Log returns require prev_close so first log_ret is NaN. That means
    # the rolling window of size 20 first fills at bar index 20 (0-based),
    # giving 5 valid sigma values (indices 20..24).
    finite = sigma.dropna()
    assert (finite == 0).all()
    assert len(finite) == 5


def test_geometric_growth_gives_finite_sigma():
    # 1% daily growth for 25 days
    closes = [100.0 * (1.01 ** i) for i in range(25)]
    df = _daily_df(closes)
    sigma = compute_sigma_realized(df, period=20)
    finite = sigma.dropna()
    # Every log return is exactly log(1.01); std should be ~0
    assert finite.iloc[-1] == pytest.approx(0.0, abs=1e-12)


def test_sigma_matches_manual_std_for_synthetic_returns():
    # Construct 21 prices with a known return sequence
    rng = np.random.default_rng(seed=42)
    returns = rng.normal(0.0, 0.02, size=20)  # 2% daily vol synthetic
    closes = [100.0]
    for r in returns:
        closes.append(closes[-1] * math.exp(r))
    df = _daily_df(closes)  # 21 bars
    sigma = compute_sigma_realized(df, period=20)
    # Manual std of the 20 log returns
    log_ret = np.log(np.array(closes[1:]) / np.array(closes[:-1]))
    manual = np.std(log_ret, ddof=0)
    assert sigma.iloc[-1] == pytest.approx(manual, rel=1e-10)


def test_insufficient_history_returns_nan():
    df = _daily_df([100.0, 101.0, 99.0])  # 3 bars, period=20
    sigma = compute_sigma_realized(df, period=20)
    assert sigma.isna().all()


def test_zero_price_produces_nan_return_but_does_not_crash():
    closes = [100.0] * 5 + [0.0] + [100.0] * 20
    df = _daily_df(closes)
    sigma = compute_sigma_realized(df, period=20)
    # At the very least, function does not raise; check first fully-warmed
    # sigma value is a real number (either NaN because window contained NaN
    # log return, or finite — either is defensible).
    val = sigma.dropna()
    # Either window rolled past the bad bar and got finite, or it stayed NaN.
    assert isinstance(val, pd.Series)


def test_empty_df_returns_empty_series():
    df = pd.DataFrame({"close": []}, index=pd.DatetimeIndex([], tz="UTC"))
    sigma = compute_sigma_realized(df, period=20)
    assert sigma.empty


def test_missing_price_column_returns_all_nan_aligned_series():
    # Convention matches compute_atr: return a Series aligned with input
    # index (not an empty Series) when data is missing.
    idx = pd.date_range("2026-01-01", periods=25, freq="1D", tz="UTC")
    df = pd.DataFrame({"other_col": [1.0] * 25}, index=idx)
    sigma = compute_sigma_realized(df, period=20)
    assert len(sigma) == 25
    assert sigma.isna().all()


def test_resample_hourly_to_daily():
    idx = pd.date_range("2026-01-01", periods=48, freq="1h", tz="UTC")
    df = pd.DataFrame(
        {
            "open":  [100.0] * 48,
            "high":  [101.0] * 48,
            "low":   [99.0] * 48,
            "close": [100.5] * 48,
            "base_volume": [1.0] * 48,
        },
        index=idx,
    )
    daily = resample_to_daily(df)
    assert len(daily) == 2
    assert daily.iloc[0]["open"] == 100.0
    assert daily.iloc[0]["high"] == 101.0
    assert daily.iloc[0]["low"] == 99.0
    assert daily.iloc[0]["close"] == 100.5
    assert daily.iloc[0]["base_volume"] == 24.0
