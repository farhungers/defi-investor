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


def test_fetch_candles_backfills_when_bitget_skips_past_start():
    """Regression: Bitget's 1m mix-candles endpoint returns the newest ~200
    bars within a wide [startTime, endTime] window, ignoring startTime. Prior
    to this fix, the forward-walk fetcher advanced past those newest bars
    and terminated, leaving the anchor region uncovered. Consequence: the
    2026-07-29 A2b v0.3.0 backfill labeled 27/27 sold-out events as
    'anchor_before_first_walk_bar'. The fetcher now detects the gap (min_ts
    > start_ms + tolerance) and backward-fills by shrinking cursor_end each
    iteration until start_ms is reached."""
    minute = 60_000
    start_ms = 0
    # end_ms aligned to the last returned bar's open time so Phase 1's
    # cursor < end_ms condition fails cleanly after page 1.
    end_ms = 599 * minute

    # Page 1 (forward walk): simulate the skip-ahead — API returns the
    # newest 200 bars (bars 400..599) instead of oldest 200 from start.
    page1 = _mk_rows(400 * minute, minute, n=200)
    # Phase 2 request #1: [0, 24000000-1] → API returns bars 200..399
    page2 = _mk_rows(200 * minute, minute, n=200)
    # Phase 2 request #2: [0, 12000000-1] → API returns bars 0..199 (start reached)
    page3 = _mk_rows(0, minute, n=200)

    fc = FakeClient(
        perp_responses=[
            FakeResponse(status_code=200, body={"code": "00000", "data": page1}),
            FakeResponse(status_code=200, body={"code": "00000", "data": page2}),
            FakeResponse(status_code=200, body={"code": "00000", "data": page3}),
        ],
    )
    df, prov = fetch_candles(
        symbol="SUSHIUSDT", start_ms=start_ms, end_ms=end_ms,
        granularity="1m", client=fc,
    )
    assert df is not None
    assert prov.market == "perp"
    assert prov.n_bars == 600
    assert prov.pages == 3
    # Crucial for the labeler: coverage now extends down to start_ms.
    assert df.index[0].value // 1_000_000 == start_ms
    # Verify the backward-walk request pattern (cursor_end shrinks each iter)
    assert fc.calls[0]["params"]["startTime"] == str(start_ms)
    assert fc.calls[0]["params"]["endTime"] == str(end_ms)
    assert fc.calls[1]["params"]["startTime"] == str(start_ms)
    assert fc.calls[1]["params"]["endTime"] == str(400 * minute - 1)
    assert fc.calls[2]["params"]["startTime"] == str(start_ms)
    assert fc.calls[2]["params"]["endTime"] == str(200 * minute - 1)


def test_fetch_candles_backfill_terminates_on_empty_response():
    """If Bitget's retention floor cuts off before we reach start_ms, the
    backward-fill must terminate on an empty response rather than looping
    forever. Coverage will be partial — the labeler correctly treats that
    as anchor_before_first_walk_bar."""
    minute = 60_000
    start_ms = 0
    end_ms = 599 * minute

    page1 = _mk_rows(400 * minute, minute, n=200)  # skip-ahead
    page2 = _mk_rows(200 * minute, minute, n=200)
    # Retention floor: next backward request returns nothing.
    empty = FakeResponse(status_code=200, body={"code": "00000", "data": []})

    fc = FakeClient(
        perp_responses=[
            FakeResponse(status_code=200, body={"code": "00000", "data": page1}),
            FakeResponse(status_code=200, body={"code": "00000", "data": page2}),
            empty,
        ],
    )
    df, prov = fetch_candles(
        symbol="X", start_ms=start_ms, end_ms=end_ms,
        granularity="1m", client=fc,
    )
    assert df is not None
    assert prov.pages == 3
    assert prov.n_bars == 400  # bars 200..599, missing 0..199
    # Earliest bar sits above start_ms — labeler will (correctly) tag unlabelable
    assert df.index[0].value // 1_000_000 == 200 * minute


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
