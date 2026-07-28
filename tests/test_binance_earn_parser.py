"""Tests for the Binance Simple Earn parser.

Fixtures are minimal envelope shapes that mimic real Binance responses
observed on 2026-07-28. If Binance rearranges its wire, these tests
should fail cleanly and point at the field that moved.
"""
from __future__ import annotations

import pytest

from defi_investor.parsers.binance_earn import (
    ParseError,
    VENUE,
    parse_homepage_response,
)


def _envelope(products: list[dict], total: int | None = None) -> dict:
    return {
        "code": "000000",
        "message": None,
        "success": True,
        "data": {"total": str(total if total is not None else len(products)), "list": products},
    }


def test_parse_flexible_product_baseline():
    prod = {
        "productId": "USDC001",
        "asset": "USDC",
        "apyRange": ["0.06684390"],
        "highestApy": "0.06684390",
        "duration": "0",
        "sellOut": False,
        "hasTierApy": True,
        "productDetailList": [
            {"productId": "USDC001", "productType": "LENDING_FLEXIBLE"}
        ],
    }
    events = parse_homepage_response(_envelope([prod]))
    assert len(events) == 1
    ev = events[0]
    assert ev.venue == VENUE == "binance"
    assert ev.product_id == "USDC001"
    assert ev.coin_name == "USDC"
    assert ev.second_biz_line == "LENDING_FLEXIBLE"
    assert ev.max_apy == pytest.approx(6.68439)  # decimal -> percent
    assert ev.min_apy == pytest.approx(6.68439)
    assert ev.lock_model is False
    assert ev.period_days is None
    assert ev.sold_out is False
    assert ev.data_quality == "complete"
    assert ev.notes == []


def test_parse_locked_product_sets_period():
    prod = {
        "productId": "NEWT090",
        "asset": "NEWT",
        "apyRange": ["0.15", "0.30"],
        "highestApy": "0.30",
        "duration": "90",
        "sellOut": False,
        "hasTierApy": False,
        "productDetailList": [{"productType": "STAKING"}],
    }
    events = parse_homepage_response(_envelope([prod]))
    assert len(events) == 1
    ev = events[0]
    assert ev.period_days == 90
    assert ev.lock_model is True
    assert ev.max_apy == pytest.approx(30.0)
    assert ev.min_apy == pytest.approx(15.0)
    assert ev.second_biz_line == "STAKING"


def test_parse_sold_out_flag_preserved():
    prod = {
        "productId": "XYZ001",
        "asset": "XYZ",
        "highestApy": "0.10",
        "duration": "0",
        "sellOut": True,
        "productDetailList": [{"productType": "LENDING_FLEXIBLE"}],
    }
    events = parse_homepage_response(_envelope([prod]))
    assert events[0].sold_out is True


def test_unknown_product_type_flagged_schema_drift():
    prod = {
        "productId": "WEIRD001",
        "asset": "WEIRD",
        "highestApy": "0.05",
        "duration": "0",
        "sellOut": False,
        "productDetailList": [{"productType": "SOME_FUTURE_KIND"}],
    }
    events = parse_homepage_response(_envelope([prod]))
    assert events[0].data_quality == "schema_drift"
    assert any("SOME_FUTURE_KIND" in n for n in events[0].notes)


def test_missing_product_id_or_asset_skipped():
    products = [
        {"productId": "", "asset": "BTC", "highestApy": "0.05"},
        {"productId": "OK1", "asset": "", "highestApy": "0.05"},
        {"productId": "OK2", "asset": "BTC", "highestApy": "0.05",
         "productDetailList": [{"productType": "LENDING_FLEXIBLE"}]},
    ]
    events = parse_homepage_response(_envelope(products))
    assert [e.product_id for e in events] == ["OK2"]


def test_empty_list_returns_empty():
    events = parse_homepage_response(_envelope([]))
    assert events == []


def test_non_dict_envelope_raises():
    with pytest.raises(ParseError):
        parse_homepage_response([])  # type: ignore[arg-type]


def test_error_code_raises():
    envelope = {"code": "099999", "message": "rate limited", "data": {"list": [], "total": "0"}}
    with pytest.raises(ParseError):
        parse_homepage_response(envelope)


def test_missing_data_object_raises():
    with pytest.raises(ParseError):
        parse_homepage_response({"code": "000000"})


def test_apy_range_normalized_to_percent():
    prod = {
        "productId": "A", "asset": "A",
        "apyRange": ["0.01", "0.05"], "highestApy": "0.05",
        "duration": "0", "sellOut": False,
        "productDetailList": [{"productType": "LENDING_FLEXIBLE"}],
    }
    ev = parse_homepage_response(_envelope([prod]))[0]
    assert ev.min_apy == pytest.approx(1.0)
    assert ev.max_apy == pytest.approx(5.0)


def test_zero_apy_is_zero_not_none():
    prod = {
        "productId": "Z", "asset": "Z",
        "highestApy": "0", "duration": "0", "sellOut": False,
        "productDetailList": [{"productType": "LENDING_FLEXIBLE"}],
    }
    ev = parse_homepage_response(_envelope([prod]))[0]
    assert ev.max_apy == 0.0


def test_lending_activity_recognized():
    prod = {
        "productId": "P", "asset": "P",
        "highestApy": "0.42", "duration": "7", "sellOut": False,
        "productDetailList": [{"productType": "LENDING_ACTIVITY"}],
    }
    ev = parse_homepage_response(_envelope([prod]))[0]
    assert ev.second_biz_line == "LENDING_ACTIVITY"
    assert ev.data_quality == "complete"
    assert ev.period_days == 7
