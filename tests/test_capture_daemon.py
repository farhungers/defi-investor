"""Tests for capture_daemon universe selection.

The daemon's async _run body is hard to unit-test (WS connections, signal
handlers, event loops), but the venue/cap selection is a pure function
we can exercise directly.
"""
from __future__ import annotations

from defi_investor.orderbook.capture_daemon import _select_universe
from defi_investor.orderbook.universe import UniverseEntry


def _e(coin: str, bg: str | None, bn: str | None) -> UniverseEntry:
    return UniverseEntry(coin_name=coin, bitget_inst_id=bg, binance_inst_id=bn, reason="test")


def test_select_universe_drops_binance_only_when_bitget_requested():
    """Regression: with ~247 coins __ABSENT__ on one venue after Session 5's
    seeder re-run, capping first pulled Bitget-absent coins into the top N
    and left `--venues bitget --max-symbols 3` with zero subscriptions.
    Filter must come before cap."""
    entries = [
        _e("AAA", None, "AAAUSDT"),         # Bitget-absent
        _e("BBB", None, "BBBUSDT"),         # Bitget-absent
        _e("CCC", None, "CCCUSDT"),         # Bitget-absent
        _e("DDD", "DDDUSDT", "DDDUSDT"),    # both
        _e("EEE", "EEEUSDT", None),         # Binance-absent
    ]
    out = _select_universe(entries, venues=["bitget"], max_symbols=3)
    assert [e.coin_name for e in out] == ["DDD", "EEE"]


def test_select_universe_cap_applies_after_filter():
    entries = [
        _e("AAA", "AAAUSDT", None),
        _e("BBB", None, "BBBUSDT"),         # dropped when only bitget requested
        _e("CCC", "CCCUSDT", None),
        _e("DDD", "DDDUSDT", None),
        _e("EEE", "EEEUSDT", None),
    ]
    out = _select_universe(entries, venues=["bitget"], max_symbols=2)
    assert [e.coin_name for e in out] == ["AAA", "CCC"]


def test_select_universe_keeps_all_when_both_venues_requested():
    entries = [
        _e("AAA", None, "AAAUSDT"),
        _e("BBB", "BBBUSDT", None),
        _e("CCC", "CCCUSDT", "CCCUSDT"),
    ]
    out = _select_universe(entries, venues=["bitget", "binance"], max_symbols=None)
    assert len(out) == 3


def test_select_universe_drops_entries_absent_on_all_requested_venues():
    """Entries missing inst_id on every requested venue are dropped even
    when max_symbols is None."""
    entries = [
        _e("AAA", "AAAUSDT", None),
        _e("BBB", None, "BBBUSDT"),   # dropped: only Binance side but venues=['bitget']
        _e("CCC", "CCCUSDT", None),
    ]
    out = _select_universe(entries, venues=["bitget"], max_symbols=None)
    assert [e.coin_name for e in out] == ["AAA", "CCC"]
