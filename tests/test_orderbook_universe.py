"""Tests for the L2 capture universe manager."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from defi_investor.orderbook.universe import _absent_marker, build_universe


class _FakeExec:
    def __init__(self, data): self.data = data


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows
        self._filters: list = []

    def select(self, *_a, **_kw): return self
    def eq(self, k, v):
        self._filters.append(("eq", k, v))
        return self
    def gte(self, k, v):
        self._filters.append(("gte", k, v))
        return self

    def execute(self) -> _FakeExec:
        # Filter rows by any applied eq/gte
        rows = list(self._rows)
        for op, k, v in self._filters:
            if op == "eq":
                rows = [r for r in rows if r.get(k) == v]
            elif op == "gte":
                rows = [r for r in rows if r.get(k) is not None and r[k] >= v]
        return _FakeExec(data=rows)


class _FakeClient:
    def __init__(self, tables: dict[str, list[dict]]):
        self._tables = tables

    def table(self, name: str) -> _FakeQuery:
        return _FakeQuery(self._tables.get(name, []))


NOW = datetime(2026, 7, 28, 12, 0, 0, tzinfo=timezone.utc)
RECENT_ISO = (NOW - timedelta(days=5)).isoformat()
OLD_ISO = (NOW - timedelta(days=45)).isoformat()


def test_active_earn_coin_included():
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "BTC", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "BTC", "status": "online"}],
    })
    u = build_universe(client, now_utc=NOW)
    assert len(u) == 1
    assert u[0].coin_name == "BTC"
    assert u[0].reason == "active_earn"
    assert u[0].bitget_inst_id == "BTCUSDT"
    assert u[0].binance_inst_id == "BTCUSDT"


def test_recent_earn_coin_included_when_sold_out_recently():
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "OGN", "sold_out": True, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "OGN", "status": "online"}],
    })
    u = build_universe(client, now_utc=NOW)
    assert len(u) == 1
    assert u[0].reason == "recent_earn"


def test_active_earn_takes_precedence_over_recent():
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "ETH", "sold_out": False, "last_seen_at": RECENT_ISO},
            {"coin_name": "ETH", "sold_out": True, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "ETH", "status": "online"}],
    })
    u = build_universe(client, now_utc=NOW)
    assert len(u) == 1
    assert u[0].reason == "active_earn"


def test_old_earn_only_excluded():
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "DEAD", "sold_out": True, "last_seen_at": OLD_ISO},
        ],
        "bitget_listings": [{"coin_name": "DEAD", "status": "online"}],
    })
    u = build_universe(client, now_utc=NOW)
    assert u == []


def test_bitget_unlisted_sets_inst_id_none_but_keeps_binance_side():
    # New semantics (2026-07-29): unlisted-on-Bitget no longer drops the
    # coin from the universe entirely. It sets bitget_inst_id=None so the
    # daemon skips Bitget for this coin but still subscribes on Binance.
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "GHOST", "sold_out": False, "last_seen_at": RECENT_ISO},
            {"coin_name": "BTC", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "BTC", "status": "online"}],
    })
    u = build_universe(client, now_utc=NOW)
    by_coin = {e.coin_name: e for e in u}
    assert set(by_coin) == {"BTC", "GHOST"}
    assert by_coin["BTC"].bitget_inst_id == "BTCUSDT"
    assert by_coin["BTC"].binance_inst_id == "BTCUSDT"
    assert by_coin["GHOST"].bitget_inst_id is None
    assert by_coin["GHOST"].binance_inst_id == "GHOSTUSDT"


def test_bitget_listing_filter_off_keeps_all():
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "GHOST", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [],
    })
    u = build_universe(client, now_utc=NOW, filter_bitget_listed=False)
    assert len(u) == 1
    assert u[0].coin_name == "GHOST"


def test_coin_name_normalized_uppercase():
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "usdc", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "USDC", "status": "online"}],
    })
    u = build_universe(client, now_utc=NOW)
    assert len(u) == 1
    assert u[0].coin_name == "USDC"


def test_offline_listing_sets_bitget_inst_none_but_keeps_binance_side():
    # New semantics (2026-07-29): offline-on-Bitget maps to
    # bitget_inst_id=None. The coin stays in the universe if Binance side
    # still resolves (default string-equality), matching the same
    # per-venue-independence rule as unlisted coins.
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "OLD", "sold_out": False, "last_seen_at": RECENT_ISO},
            {"coin_name": "BTC", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [
            {"coin_name": "OLD", "status": "offline"},
            {"coin_name": "BTC", "status": "online"},
        ],
    })
    u = build_universe(client, now_utc=NOW)
    by_coin = {e.coin_name: e for e in u}
    assert set(by_coin) == {"BTC", "OLD"}
    assert by_coin["OLD"].bitget_inst_id is None
    assert by_coin["OLD"].binance_inst_id == "OLDUSDT"


def test_empty_result_when_no_earn_data():
    client = _FakeClient({"earn_events": [], "bitget_listings": []})
    u = build_universe(client, now_utc=NOW)
    assert u == []


def test_coin_map_override_replaces_default_inst_id():
    # earn '1000CAT' should map to Bitget '1000CATSUSDT' via venue_coin_map
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "1000CAT", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "1000CAT", "status": "online"}],
    })
    overrides = {("bitget", "1000CAT"): "1000CATSUSDT"}
    u = build_universe(client, now_utc=NOW, coin_map_overrides=overrides)
    assert len(u) == 1
    assert u[0].bitget_inst_id == "1000CATSUSDT"
    # Binance had no override → default string-equality
    assert u[0].binance_inst_id == "1000CATUSDT"


def test_coin_map_override_only_applies_to_named_venue():
    # An override for bitget shouldn't leak into the binance inst_id.
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "PEPE", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "PEPE", "status": "online"}],
    })
    overrides = {
        ("bitget", "PEPE"): "1000PEPEUSDT",
        ("binance", "PEPE"): "PEPEUSDT",
    }
    u = build_universe(client, now_utc=NOW, coin_map_overrides=overrides)
    assert u[0].bitget_inst_id == "1000PEPEUSDT"
    assert u[0].binance_inst_id == "PEPEUSDT"


def test_absent_sentinel_bitget_sets_inst_id_none():
    # A venue_coin_map row with the absent-sentinel prefix must map to
    # bitget_inst_id=None (per-coin encoded so many absents can coexist
    # under the (venue, venue_coin) composite PK).
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "EARNONLY", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "EARNONLY", "status": "online"}],
    })
    overrides = {("bitget", "EARNONLY"): _absent_marker("EARNONLY")}
    u = build_universe(client, now_utc=NOW, coin_map_overrides=overrides)
    assert len(u) == 1
    assert u[0].bitget_inst_id is None
    assert u[0].binance_inst_id == "EARNONLYUSDT"


def test_absent_sentinel_binance_sets_inst_id_none():
    # Binance has no listings table, so absence is only signalled via the
    # venue_coin_map sentinel.
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "BITONLY", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [{"coin_name": "BITONLY", "status": "online"}],
    })
    overrides = {("binance", "BITONLY"): _absent_marker("BITONLY")}
    u = build_universe(client, now_utc=NOW, coin_map_overrides=overrides)
    assert len(u) == 1
    assert u[0].bitget_inst_id == "BITONLYUSDT"
    assert u[0].binance_inst_id is None


def test_absent_on_both_venues_drops_entry():
    # If a coin has no counterpart on either venue, the entry has no
    # subscription target and should not appear in the universe at all.
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "NOWHERE", "sold_out": False, "last_seen_at": RECENT_ISO},
            {"coin_name": "BTC", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [
            {"coin_name": "BTC", "status": "online"},
            {"coin_name": "NOWHERE", "status": "online"},
        ],
    })
    overrides = {
        ("bitget", "NOWHERE"): _absent_marker("NOWHERE"),
        ("binance", "NOWHERE"): _absent_marker("NOWHERE"),
    }
    u = build_universe(client, now_utc=NOW, coin_map_overrides=overrides)
    coins = {e.coin_name for e in u}
    assert coins == {"BTC"}


def test_empty_bitget_listings_falls_back_to_no_filter():
    # If bitget_listings has zero online rows, the filter is skipped
    # rather than dropping every coin (regression guard against the
    # 2026-07-28 bug where listings scraper hadn't run and universe
    # went silently to 0).
    client = _FakeClient({
        "earn_events": [
            {"coin_name": "BTC", "sold_out": False, "last_seen_at": RECENT_ISO},
        ],
        "bitget_listings": [],
    })
    u = build_universe(client, now_utc=NOW, filter_bitget_listed=True)
    assert len(u) == 1
    assert u[0].coin_name == "BTC"
