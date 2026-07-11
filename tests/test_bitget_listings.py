"""Tests for the Bitget spot-listings scraper (control-arm data source).

No network; uses httpx.MockTransport.
"""
from __future__ import annotations

import httpx
import pytest

from defi_investor.bitget_listings import (
    BitgetListing,
    fetch_spot_symbols,
    parse_symbol,
    snapshot_listings,
)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- parse_symbol ----------------------------------------------------------


def test_parse_symbol_happy_path():
    entry = {
        "symbol": "GOATUSDT", "baseCoin": "goat", "quoteCoin": "USDT",
        "status": "online", "openTime": "1729314000000", "offTime": "",
    }
    l = parse_symbol(entry)
    assert l is not None
    assert l.symbol == "GOATUSDT"
    assert l.coin_name == "GOAT"      # uppercased
    assert l.quote_coin == "USDT"
    assert l.listing_ts.startswith("2024-10-19")
    assert l.status == "online"
    assert l.off_ts is None


def test_parse_symbol_offline_with_off_ts():
    entry = {
        "symbol": "OLDUSDT", "baseCoin": "OLD", "quoteCoin": "USDT",
        "status": "offline", "openTime": "1600000000000",
        "offTime": "1700000000000",
    }
    l = parse_symbol(entry)
    assert l is not None
    assert l.status == "offline"
    assert l.off_ts is not None
    assert l.off_ts.startswith("2023-11-14")


def test_parse_symbol_none_on_missing_fields():
    assert parse_symbol({}) is None
    assert parse_symbol({"symbol": "X", "baseCoin": "X"}) is None
    assert parse_symbol({"symbol": "X", "baseCoin": "X",
                         "quoteCoin": "USDT"}) is None  # no openTime


def test_parse_symbol_none_on_zero_open_time():
    entry = {
        "symbol": "X", "baseCoin": "X", "quoteCoin": "USDT",
        "openTime": "0", "status": "online",
    }
    assert parse_symbol(entry) is None


def test_parse_symbol_none_on_non_numeric_open_time():
    entry = {
        "symbol": "X", "baseCoin": "X", "quoteCoin": "USDT",
        "openTime": "n/a", "status": "online",
    }
    assert parse_symbol(entry) is None


# --- fetch_spot_symbols ----------------------------------------------------


_SAMPLE_RESPONSE = {
    "code": "00000", "msg": "success", "requestTime": 1,
    "data": [
        {"symbol": "GOATUSDT", "baseCoin": "GOAT", "quoteCoin": "USDT",
         "status": "online", "openTime": "1729314000000", "offTime": ""},
        {"symbol": "LABUSDT", "baseCoin": "LAB", "quoteCoin": "USDT",
         "status": "online", "openTime": "1750000000000", "offTime": ""},
        {"symbol": "BROKEN", "baseCoin": "", "quoteCoin": "USDT",  # skipped
         "status": "online", "openTime": "1500000000000"},
    ],
}


def test_fetch_spot_symbols_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SAMPLE_RESPONSE)

    with _mock_client(handler) as client:
        listings, status, err = fetch_spot_symbols(client=client)
    assert status == 200
    assert err is None
    assert len(listings) == 2   # broken entry skipped
    assert {l.symbol for l in listings} == {"GOATUSDT", "LABUSDT"}


def test_fetch_spot_symbols_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="unavailable")

    with _mock_client(handler) as client:
        listings, status, err = fetch_spot_symbols(client=client)
    assert listings == []
    assert status == 503
    assert err is not None and "non_200" in err


def test_fetch_spot_symbols_invalid_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>oops</html>")

    with _mock_client(handler) as client:
        listings, status, err = fetch_spot_symbols(client=client)
    assert listings == []
    assert err == "invalid_json"


def test_fetch_spot_symbols_api_error_code():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"code": "40000", "msg": "bad request",
                                         "data": None})

    with _mock_client(handler) as client:
        listings, status, err = fetch_spot_symbols(client=client)
    assert listings == []
    assert err is not None and "40000" in err


def test_fetch_spot_symbols_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    with _mock_client(handler) as client:
        listings, status, err = fetch_spot_symbols(client=client)
    assert listings == []
    assert status == 0
    assert err is not None and "http_error" in err


# --- snapshot_listings -----------------------------------------------------


def test_snapshot_listings_reports_stats():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_SAMPLE_RESPONSE)

    with _mock_client(handler) as client:
        listings, stats = snapshot_listings(
            observed_at="2026-07-11T00:00:00+00:00", client=client,
        )
    assert stats["n_fetched"] == 2
    assert stats["n_online"] == 2
    assert stats["n_offline"] == 0
    assert stats["n_usdt_quoted"] == 2
    assert stats["error"] is None


# --- BitgetListing.to_row --------------------------------------------------


def test_to_row_carries_provenance_and_source():
    l = BitgetListing(
        symbol="GOATUSDT", coin_name="GOAT", quote_coin="USDT",
        listing_ts="2024-10-19T05:00:00+00:00", status="online", off_ts=None,
    )
    row = l.to_row(
        first_seen_at="2026-07-11T00:00:00+00:00",
        last_seen_at="2026-07-11T03:00:00+00:00",
    )
    assert row == {
        "symbol": "GOATUSDT", "coin_name": "GOAT", "quote_coin": "USDT",
        "listing_ts": "2024-10-19T05:00:00+00:00",
        "status": "online", "off_ts": None,
        "first_seen_at": "2026-07-11T00:00:00+00:00",
        "last_seen_at": "2026-07-11T03:00:00+00:00",
        "snapshot_source": "spot_symbols",
    }
