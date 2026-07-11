"""Tests for tokenomist.ai SSR vest-unlock scraper. No network."""
from __future__ import annotations

import httpx
import pytest

from defi_investor.vest_unlocks import (
    NextUnlockSnapshot,
    fetch_next_unlock,
    parse_description,
    resolve_slug,
    snapshot_universe,
)


def _mock_client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler), follow_redirects=True)


# --- parse_description -----------------------------------------------------


ARB_DESC_HTML = (
    '<html><meta name="description" content="Arbitrum (ARB) tokenomics '
    'intelligence: next unlock on July 16, 2026 releasing 92,645,833 ARB '
    '(~$8,528,604.802648). Currently 56.28% of total supply released."/></html>'
)


UNDEFINED_DESC_HTML = (
    '<html>{"description":"LAB (LAB) tokenomics intelligence: next unlock on '
    'undefined releasing undefined LAB (~$undefined). Currently undefined% of '
    'total supply released."}</html>'
)


NO_META_HTML = "<html><head><title>nothing here</title></head><body></body></html>"


def test_parse_description_extracts_tracked_unlock():
    status, iso, amt, usd = parse_description(ARB_DESC_HTML)
    assert status == "tracked_with_unlock"
    assert iso == "2026-07-16T00:00:00+00:00"
    assert amt == pytest.approx(92_645_833.0)
    assert usd == pytest.approx(8_528_604.802648)


def test_parse_description_recognizes_undefined_as_no_upcoming():
    status, iso, amt, usd = parse_description(UNDEFINED_DESC_HTML)
    assert status == "no_upcoming_unlock"
    assert iso is None
    assert amt is None
    assert usd is None


def test_parse_description_missing_meta_is_malformed():
    status, *_ = parse_description(NO_META_HTML)
    assert status == "malformed"


def test_parse_description_meta_without_next_unlock_is_malformed():
    html = ('<meta name="description" content="Some other project description'
            ' that does not mention the key phrase."/>')
    status, *_ = parse_description(html)
    assert status == "malformed"


# --- resolve_slug ----------------------------------------------------------


def test_resolve_slug_uses_override_when_present():
    assert resolve_slug("ARB") == "arbitrum"
    assert resolve_slug("arb") == "arbitrum"


def test_resolve_slug_falls_back_to_lowercase():
    assert resolve_slug("LAB") == "lab"
    assert resolve_slug("ThisIsANewSymbol") == "thisisanewsymbol"


# --- fetch_next_unlock -----------------------------------------------------


def test_fetch_next_unlock_happy_path():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/arbitrum"
        return httpx.Response(200, text=ARB_DESC_HTML)

    with _mock_client(handler) as client:
        snap = fetch_next_unlock(
            "ARB", snapped_at="2026-07-11T00:00:00+00:00", client=client,
        )
    assert snap.status == "tracked_with_unlock"
    assert snap.tokenomist_slug == "arbitrum"
    assert snap.next_unlock_at == "2026-07-16T00:00:00+00:00"
    assert snap.next_unlock_amount == pytest.approx(92_645_833.0)
    assert snap.http_status == 200


def test_fetch_next_unlock_untracked_on_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, text="not found")

    with _mock_client(handler) as client:
        snap = fetch_next_unlock("GHOST", client=client)
    assert snap.status == "untracked"
    assert snap.http_status == 404
    assert snap.next_unlock_at is None


def test_fetch_next_unlock_no_upcoming_on_undefined():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=UNDEFINED_DESC_HTML)

    with _mock_client(handler) as client:
        snap = fetch_next_unlock("LAB", client=client)
    assert snap.status == "no_upcoming_unlock"
    assert snap.next_unlock_at is None


def test_fetch_next_unlock_error_on_non_200_non_404():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="server error")

    with _mock_client(handler) as client:
        snap = fetch_next_unlock("LAB", client=client)
    assert snap.status == "error"
    assert snap.http_status == 500


def test_fetch_next_unlock_error_on_http_exception():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("network down")

    with _mock_client(handler) as client:
        snap = fetch_next_unlock("LAB", client=client)
    assert snap.status == "error"
    assert snap.http_status == 0
    assert snap.error is not None and "http_error" in snap.error


def test_fetch_next_unlock_malformed_on_missing_meta():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=NO_META_HTML)

    with _mock_client(handler) as client:
        snap = fetch_next_unlock("LAB", client=client)
    assert snap.status == "malformed"


def test_to_row_shape():
    snap = NextUnlockSnapshot(
        coin_name="ARB", snapped_at="2026-07-11T00:00:00+00:00",
        tokenomist_slug="arbitrum", status="tracked_with_unlock",
        next_unlock_at="2026-07-16T00:00:00+00:00",
        next_unlock_amount=92_645_833.0, next_unlock_usd=8_528_604.80,
        http_status=200, error=None,
    )
    row = snap.to_row()
    assert row == {
        "coin_name": "ARB",
        "snapped_at": "2026-07-11T00:00:00+00:00",
        "tokenomist_slug": "arbitrum",
        "status": "tracked_with_unlock",
        "next_unlock_at": "2026-07-16T00:00:00+00:00",
        "next_unlock_amount": 92_645_833.0,
        "next_unlock_usd": 8_528_604.80,
        "http_status": 200,
        "error": None,
    }


# --- snapshot_universe -----------------------------------------------------


def test_snapshot_universe_dedupes_and_uppercases():
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        return httpx.Response(200, text=ARB_DESC_HTML)

    with _mock_client(handler) as client:
        snaps = snapshot_universe(
            ["arb", "ARB", "LAB", "", None],
            snapped_at="2026-07-11T00:00:00+00:00",
            client=client, inter_call_sleep_s=0,
        )
    # Two distinct: ARB (mapped to arbitrum) and LAB (lab).
    assert calls == ["/arbitrum", "/lab"]
    assert [s.coin_name for s in snaps] == ["ARB", "LAB"]
    assert all(s.snapped_at == "2026-07-11T00:00:00+00:00" for s in snaps)


def test_snapshot_universe_honors_max_coins_cap():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=UNDEFINED_DESC_HTML)

    with _mock_client(handler) as client:
        snaps = snapshot_universe(
            [f"COIN{i}" for i in range(10)],
            client=client, inter_call_sleep_s=0,
            max_coins=3,
        )
    assert len(snaps) == 3
