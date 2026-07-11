"""Tests for the OI-snapshot fetcher. No network — httpx.MockTransport only."""
from __future__ import annotations

import json

import httpx
import pytest

from defi_investor.oi_snapshots import (
    OISnapshot,
    fetch_current_oi,
    snapshot_universe,
)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- fetch_current_oi ------------------------------------------------------


def test_fetch_current_oi_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert "symbol=LABUSDT" in str(request.url)
        assert "productType=USDT-FUTURES" in str(request.url)
        return httpx.Response(200, json={
            "code": "00000", "msg": "success", "requestTime": 1,
            "data": {"openInterestList": [{"symbol": "LABUSDT",
                                            "size": "10265697"}],
                     "ts": "1"},
        })

    with _mock_client(handler) as client:
        snap = fetch_current_oi("LAB", snapped_at="2026-07-11T00:00:00+00:00",
                                client=client)
    assert snap.market == "perp"
    assert snap.oi_base == pytest.approx(10265697.0)
    assert snap.error is None
    assert snap.http_status == 200
    assert snap.symbol == "LABUSDT"
    assert snap.snapped_at == "2026-07-11T00:00:00+00:00"


def test_fetch_current_oi_nonexistent_symbol_records_gap_row():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "40034",
            "msg": "Parameter GHOSTUSDT does not exist",
            "requestTime": 1, "data": None,
        })

    with _mock_client(handler) as client:
        snap = fetch_current_oi("GHOST", client=client)
    assert snap.market == "none"
    assert snap.oi_base is None
    assert snap.error is not None
    assert "40034" in snap.error
    assert snap.http_status == 200


def test_fetch_current_oi_non_200():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="Too Many Requests")

    with _mock_client(handler) as client:
        snap = fetch_current_oi("LAB", client=client)
    assert snap.market == "none"
    assert snap.oi_base is None
    assert snap.http_status == 429
    assert snap.error is not None and "non_200" in snap.error


def test_fetch_current_oi_invalid_json():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html>not-json</html>")

    with _mock_client(handler) as client:
        snap = fetch_current_oi("LAB", client=client)
    assert snap.market == "none"
    assert snap.oi_base is None
    assert snap.error == "invalid_json"


def test_fetch_current_oi_http_error():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    with _mock_client(handler) as client:
        snap = fetch_current_oi("LAB", client=client)
    assert snap.market == "none"
    assert snap.oi_base is None
    assert snap.http_status == 0
    assert snap.error is not None and "http_error" in snap.error


def test_fetch_current_oi_empty_openInterestList():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000", "msg": "success", "requestTime": 1,
            "data": {"openInterestList": [], "ts": "1"},
        })

    with _mock_client(handler) as client:
        snap = fetch_current_oi("LAB", client=client)
    assert snap.market == "perp"
    assert snap.oi_base is None
    assert snap.error == "empty_openInterestList"


def test_fetch_current_oi_unparsable_size():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000", "msg": "success", "requestTime": 1,
            "data": {"openInterestList": [{"symbol": "LABUSDT", "size": "n/a"}],
                     "ts": "1"},
        })

    with _mock_client(handler) as client:
        snap = fetch_current_oi("LAB", client=client)
    assert snap.market == "perp"
    assert snap.oi_base is None
    assert snap.error == "unparsable_size"


def test_snapshot_to_row_shape():
    snap = OISnapshot(
        coin_name="LAB", snapped_at="2026-07-11T00:00:00+00:00",
        symbol="LABUSDT", market="perp", oi_base=1234.5,
        http_status=200, error=None,
    )
    row = snap.to_row()
    assert row == {
        "coin_name": "LAB", "snapped_at": "2026-07-11T00:00:00+00:00",
        "symbol": "LABUSDT", "market": "perp", "oi_base": 1234.5,
        "http_status": 200, "error": None,
    }


# --- snapshot_universe -----------------------------------------------------


def test_snapshot_universe_dedupes_and_uppercases():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        # Record the symbol param
        q = dict(request.url.params)
        calls.append(q["symbol"])
        return httpx.Response(200, json={
            "code": "00000", "msg": "success", "requestTime": 1,
            "data": {"openInterestList": [{"symbol": q["symbol"], "size": "1"}],
                     "ts": "1"},
        })

    with _mock_client(handler) as client:
        snaps = snapshot_universe(
            ["lab", "LAB", "OGN", "", None],  # dupes + noise
            snapped_at="2026-07-11T00:00:00+00:00",
            client=client, inter_call_sleep_s=0,
        )
    assert calls == ["LABUSDT", "OGNUSDT"]
    assert [s.coin_name for s in snaps] == ["LAB", "OGN"]
    assert all(s.snapped_at == "2026-07-11T00:00:00+00:00" for s in snaps)


def test_snapshot_universe_honors_max_coins_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={
            "code": "00000", "msg": "success", "requestTime": 1,
            "data": {"openInterestList": [
                {"symbol": dict(request.url.params)["symbol"], "size": "1"}
            ], "ts": "1"},
        })

    with _mock_client(handler) as client:
        snaps = snapshot_universe(
            [f"COIN{i}" for i in range(10)],
            snapped_at="2026-07-11T00:00:00+00:00",
            client=client, inter_call_sleep_s=0,
            max_coins=3,
        )
    assert len(snaps) == 3
