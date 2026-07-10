"""Triple-barrier labeler tests. No network — inject candle fetcher output."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd
import pytest

from defi_investor import labeler as lbl_mod
from defi_investor.candles import CandleFetch
from defi_investor.labeler import LABELER_VERSION, LabelRow, label_event
from defi_investor.models import EarnEvent


def _sold_out_event(pid="p1", coin="LAB", anchor_iso="2026-05-15T00:00:00+00:00") -> EarnEvent:
    return EarnEvent(
        product_id=pid,
        coin_name=coin,
        second_biz_line="Savings",
        max_apy=365.0,
        status=6,
        sold_out=True,
        first_seen_at=anchor_iso,
        last_seen_at=anchor_iso,
        sold_out_first_seen_at=anchor_iso,
        start_time="2026-05-01T00:00:00+00:00",
    )


def _mk_df(prices: list[tuple[str, float, float, float, float]]) -> pd.DataFrame:
    """Build a 4H DataFrame from [(ts_iso, o, h, l, c), ...]."""
    idx = pd.to_datetime([t for t, *_ in prices], utc=True)
    df = pd.DataFrame({
        "open":  [o for _, o, _, _, _ in prices],
        "high":  [h for _, _, h, _, _ in prices],
        "low":   [l for _, _, _, l, _ in prices],
        "close": [c for _, _, _, _, c in prices],
        "base_vol":  1000.0,
        "quote_vol": 100000.0,
    }, index=idx)
    return df


def _flat_warmup(anchor: datetime, n_bars: int = 30, price: float = 100.0,
                 range_: float = 4.0) -> list[tuple[str, float, float, float, float]]:
    """Enough prior bars at fixed price to warm ATR up to a known value."""
    bars = []
    # Start bars 4h*n before anchor, going forward
    for i in range(n_bars):
        ts = (anchor - timedelta(hours=4 * (n_bars - i))).isoformat()
        bars.append((ts, price, price + range_ / 2, price - range_ / 2, price))
    return bars


def _patch_fetch(monkeypatch, df: pd.DataFrame, market: str = "perp"):
    prov = CandleFetch(
        url="fake", market=market, symbol="X", granularity="4H",
        start_ms=0, end_ms=1, n_bars=len(df),
        fetched_at="2026-07-10T00:00:00+00:00", http_status=200,
    )

    def fake(**kw):
        return df, prov

    monkeypatch.setattr(lbl_mod, "fetch_candles", fake)


# --- Guard rails -----------------------------------------------------------


def test_returns_none_for_non_sold_out_event(monkeypatch):
    ev = _sold_out_event()
    ev.sold_out = False
    ev.status = 2
    assert label_event(ev) is None


def test_missing_anchor_ts_returns_unlabelable(monkeypatch):
    ev = _sold_out_event()
    ev.sold_out_first_seen_at = None
    _patch_fetch(monkeypatch, pd.DataFrame())
    row = label_event(ev)
    assert isinstance(row, LabelRow)
    assert row.label is None
    assert row.unlabelable_reason == "anchor_missing"


def test_no_candles_marks_unlabelable(monkeypatch):
    ev = _sold_out_event()
    _patch_fetch(monkeypatch, pd.DataFrame(), market="none")
    row = label_event(ev)
    assert row.label is None
    assert row.unlabelable_reason == "no_candles_available"
    assert row.market == "none"


def test_insufficient_warmup_marks_unlabelable(monkeypatch):
    """Only 5 bars before anchor — ATR(24) undefined at anchor."""
    anchor = datetime.fromisoformat("2026-05-15T00:00:00+00:00")
    ev = _sold_out_event(anchor_iso=anchor.isoformat())
    warmup = _flat_warmup(anchor, n_bars=5, price=100.0, range_=4.0)
    _patch_fetch(monkeypatch, _mk_df(warmup))
    row = label_event(ev)
    assert row.label is None
    assert row.unlabelable_reason == "atr_undefined_at_anchor"


# --- Barrier resolution ---------------------------------------------------


def test_dump_within_horizon_labels_plus_one(monkeypatch):
    """Constant-vol warmup, then a hard downside break → T1_DOWN → label=+1."""
    anchor = datetime.fromisoformat("2026-05-15T00:00:00+00:00")
    ev = _sold_out_event(anchor_iso=anchor.isoformat())
    warmup = _flat_warmup(anchor, n_bars=30, price=100.0, range_=4.0)
    # After anchor, price crashes — bar 3 posts low far below down barrier
    after = []
    for i in range(1, 12):
        ts = (anchor + timedelta(hours=4 * i)).isoformat()
        # low goes very low on bar 3
        if i == 3:
            after.append((ts, 99.0, 100.0, 50.0, 60.0))
        else:
            after.append((ts, 99.0, 101.0, 97.0, 98.0))
    _patch_fetch(monkeypatch, _mk_df(warmup + after))
    row = label_event(ev, horizon_days=7)
    assert row.label == +1
    assert row.barrier_hit == "T1_DOWN"
    assert row.realized_r > 0


def test_pump_within_horizon_labels_minus_one(monkeypatch):
    anchor = datetime.fromisoformat("2026-05-15T00:00:00+00:00")
    ev = _sold_out_event(anchor_iso=anchor.isoformat())
    warmup = _flat_warmup(anchor, n_bars=30, price=100.0, range_=4.0)
    after = []
    for i in range(1, 12):
        ts = (anchor + timedelta(hours=4 * i)).isoformat()
        if i == 4:
            after.append((ts, 101.0, 200.0, 100.0, 195.0))  # blowout up
        else:
            after.append((ts, 101.0, 103.0, 99.0, 102.0))
    _patch_fetch(monkeypatch, _mk_df(warmup + after))
    row = label_event(ev, horizon_days=7)
    assert row.label == -1
    assert row.barrier_hit == "T1_UP"
    # H1 predicts dump, this is a pump — realized_r should be negative
    assert row.realized_r < 0


def test_no_barrier_hit_within_horizon_labels_zero(monkeypatch):
    """Price stays inside barriers for the full horizon → label = 0."""
    anchor = datetime.fromisoformat("2026-05-15T00:00:00+00:00")
    ev = _sold_out_event(anchor_iso=anchor.isoformat())
    warmup = _flat_warmup(anchor, n_bars=30, price=100.0, range_=4.0)
    # 7 days = 42 4h bars; extra slack for T2 candle
    after = []
    for i in range(1, 55):
        ts = (anchor + timedelta(hours=4 * i)).isoformat()
        after.append((ts, 100.5, 101.0, 99.8, 100.4))  # tight range, no break
    _patch_fetch(monkeypatch, _mk_df(warmup + after))
    row = label_event(ev, horizon_days=7)
    assert row.label == 0
    assert row.barrier_hit == "T2"
    assert row.realized_r == 0.0


def test_horizon_not_yet_resolved_marks_unlabelable(monkeypatch):
    """Anchor recent, only 24h of post-anchor candles → cannot resolve T2."""
    anchor = datetime.fromisoformat("2026-05-15T00:00:00+00:00")
    ev = _sold_out_event(anchor_iso=anchor.isoformat())
    warmup = _flat_warmup(anchor, n_bars=30, price=100.0, range_=4.0)
    after = []
    for i in range(1, 7):  # only ~24h post-anchor
        ts = (anchor + timedelta(hours=4 * i)).isoformat()
        after.append((ts, 100.5, 101.0, 99.8, 100.4))
    _patch_fetch(monkeypatch, _mk_df(warmup + after))
    row = label_event(ev, horizon_days=7)
    assert row.label is None
    assert row.unlabelable_reason == "horizon_not_yet_resolved"


def test_label_row_carries_provenance_and_version(monkeypatch):
    anchor = datetime.fromisoformat("2026-05-15T00:00:00+00:00")
    ev = _sold_out_event(anchor_iso=anchor.isoformat())
    warmup = _flat_warmup(anchor, n_bars=30, price=100.0, range_=4.0)
    after = []
    for i in range(1, 55):
        ts = (anchor + timedelta(hours=4 * i)).isoformat()
        after.append((ts, 100.5, 101.0, 99.8, 100.4))
    _patch_fetch(monkeypatch, _mk_df(warmup + after))
    row = label_event(ev, horizon_days=7)
    assert row.labeler_version == LABELER_VERSION
    assert row.market == "perp"
    assert row.anchor_close_price is not None
    assert row.atr_4h_at_anchor is not None
    assert row.candles_provenance["market"] == "perp"
