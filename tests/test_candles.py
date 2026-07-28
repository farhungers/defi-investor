"""Tests for the Bitget candle fetcher. No network — fake httpx client."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pandas as pd
import pytest

from defi_investor.candles import (
    PERP_URL,
    SPOT_URL,
    compute_atr,
    fetch_candles,
    _to_frame,
)


@dataclass
class FakeResponse:
    status_code: int = 200
    body: dict = field(default_factory=dict)
    text_: str = ""

    def json(self):
        return self.body

    @property
    def text(self):
        return self.text_


@dataclass
class FakeClient:
    """Configurable fake: maps (url,) -> queue of responses."""
    perp_responses: list = field(default_factory=list)
    spot_responses: list = field(default_factory=list)
    calls: list = field(default_factory=list)

    def get(self, url, params=None, timeout=None):
        self.calls.append({"url": url, "params": dict(params or {})})
        queue = self.perp_responses if url == PERP_URL else self.spot_responses
        if not queue:
            return FakeResponse(status_code=200, body={"code": "00000", "data": []})
        return queue.pop(0)

    def close(self):
        pass


# --- helpers ---------------------------------------------------------------


def _mk_rows(start_ms: int, step_ms: int, n: int, base_price: float = 100.0):
    rows = []
    for i in range(n):
        o = base_price + i
        h = o + 2
        low = o - 2
        c = o + 1
        rows.append([str(start_ms + i * step_ms), str(o), str(h), str(low), str(c), "1000", "100000"])
    return rows


# --- _to_frame -------------------------------------------------------------


def test_to_frame_empty_returns_empty_frame():
    df = _to_frame([])
    assert df.empty
    assert set(df.columns) == {"open", "high", "low", "close", "base_vol", "quote_vol"}


def test_to_frame_types_numeric_and_index_is_utc():
    df = _to_frame(_mk_rows(1_700_000_000_000, step_ms=14_400_000, n=3))
    assert df["open"].dtype.kind == "f"
    assert df.index.tz is not None
    assert df.index[0] < df.index[1] < df.index[2]


# --- fetch_candles: perp path -------------------------------------------


def test_fetch_candles_perp_returns_frame_and_provenance():
    fc = FakeClient(
        perp_responses=[FakeResponse(status_code=200, body={
            "code": "00000",
            "data": _mk_rows(1_700_000_000_000, 14_400_000, n=3),
        })],
    )
    df, prov = fetch_candles(
        symbol="LABUSDT", start_ms=1_700_000_000_000,
        end_ms=1_700_000_000_000 + 3 * 14_400_000, granularity="4H", client=fc,
    )
    assert df is not None
    assert len(df) == 3
    assert prov.market == "perp"
    assert prov.n_bars == 3
    assert prov.error is None
    # First call went to the perp URL
    assert fc.calls[0]["url"] == PERP_URL
    assert fc.calls[0]["params"]["productType"] == "USDT-FUTURES"


# --- fetch_candles: spot fallback ------------------------------------------


def test_fetch_candles_falls_back_to_spot_on_empty_perp():
    fc = FakeClient(
        perp_responses=[FakeResponse(status_code=200, body={"code": "00000", "data": []})],
        spot_responses=[FakeResponse(status_code=200, body={
            "code": "00000", "data": _mk_rows(1_700_000_000_000, 14_400_000, n=2),
        })],
    )
    df, prov = fetch_candles(
        symbol="RARECOIN", start_ms=1_700_000_000_000,
        end_ms=1_700_000_000_000 + 2 * 14_400_000, granularity="4H", client=fc,
    )
    assert df is not None
    assert prov.market == "spot"
    assert len(df) == 2
    # Called perp, then spot
    assert fc.calls[0]["url"] == PERP_URL
    assert fc.calls[-1]["url"] == SPOT_URL


def test_fetch_candles_translates_granularity_for_spot_fallback():
    """Bitget spot uses 1min/4h/1day; perp uses 1m/4H/1D. The fallback
    must translate. Regression guard for the silent-empty-fallback bug
    caught 2026-07-28 by scripts/probe_bitget_candle_retention.py."""
    fc = FakeClient(
        perp_responses=[FakeResponse(status_code=200, body={"code": "00000", "data": []})],
        spot_responses=[FakeResponse(status_code=200, body={
            "code": "00000", "data": _mk_rows(1_700_000_000_000, 14_400_000, n=1),
        })],
    )
    df, prov = fetch_candles(
        symbol="RARECOIN", start_ms=1_700_000_000_000,
        end_ms=1_700_000_000_000 + 14_400_000, granularity="4H", client=fc,
    )
    assert df is not None
    # Perp call used the '4H' string as-is
    assert fc.calls[0]["params"]["granularity"] == "4H"
    # Spot fallback translated to '4h'
    assert fc.calls[-1]["params"]["granularity"] == "4h"


def test_fetch_candles_returns_none_when_neither_market_has_data():
    fc = FakeClient(
        perp_responses=[FakeResponse(status_code=200, body={"code": "00000", "data": []})],
        spot_responses=[FakeResponse(status_code=200, body={"code": "00000", "data": []})],
    )
    df, prov = fetch_candles(
        symbol="GHOST", start_ms=1_700_000_000_000,
        end_ms=1_700_000_000_000 + 3600_000, granularity="1H", client=fc,
    )
    assert df is None
    assert prov.market == "none"
    assert prov.n_bars == 0


def test_fetch_candles_records_api_error_in_provenance():
    fc = FakeClient(
        perp_responses=[FakeResponse(status_code=200, body={
            "code": "40001", "msg": "symbol not found", "data": [],
        })],
        spot_responses=[FakeResponse(status_code=200, body={
            "code": "40001", "msg": "symbol not found", "data": [],
        })],
    )
    df, prov = fetch_candles(
        symbol="NOPE", start_ms=1_700_000_000_000,
        end_ms=1_700_000_000_000 + 3600_000, client=fc,
    )
    assert df is None
    assert prov.error is not None
    assert "40001" in prov.error


# --- pagination -----------------------------------------------------------


def test_fetch_candles_paginates_across_windows():
    # Two full pages of 200 bars each — simulate cursor advancing
    step = 14_400_000
    page1 = _mk_rows(1_700_000_000_000, step, n=200)
    page2 = _mk_rows(1_700_000_000_000 + 200 * step, step, n=50)  # partial → done
    fc = FakeClient(
        perp_responses=[
            FakeResponse(status_code=200, body={"code": "00000", "data": page1}),
            FakeResponse(status_code=200, body={"code": "00000", "data": page2}),
        ],
    )
    df, prov = fetch_candles(
        symbol="X", start_ms=1_700_000_000_000,
        end_ms=1_700_000_000_000 + 250 * step, client=fc,
    )
    assert df is not None
    assert prov.pages == 2
    assert prov.n_bars == 250


# --- compute_atr -----------------------------------------------------------


def test_compute_atr_flat_price_is_zero_after_warmup():
    # Constant OHLC → true range = 0 → ATR = 0
    idx = pd.date_range("2026-01-01", periods=30, freq="4h", tz="UTC")
    df = pd.DataFrame({
        "open": 100.0, "high": 100.0, "low": 100.0, "close": 100.0,
        "base_vol": 1.0, "quote_vol": 100.0,
    }, index=idx)
    atr = compute_atr(df, period=24)
    # First 23 bars NaN, from bar 24 onward ATR = 0
    assert pd.isna(atr.iloc[0])
    assert atr.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_compute_atr_positive_for_volatile_series():
    idx = pd.date_range("2026-01-01", periods=30, freq="4h", tz="UTC")
    # H-L range = 10 each bar → ATR should converge to ~10
    df = pd.DataFrame({
        "open": [100 + i for i in range(30)],
        "high": [105 + i for i in range(30)],
        "low": [95 + i for i in range(30)],
        "close": [102 + i for i in range(30)],
        "base_vol": 1.0, "quote_vol": 100.0,
    }, index=idx)
    atr = compute_atr(df, period=24)
    assert atr.iloc[-1] > 5  # meaningfully positive after warmup


def test_compute_atr_empty_returns_empty_series():
    atr = compute_atr(pd.DataFrame(), period=24)
    assert atr.empty
