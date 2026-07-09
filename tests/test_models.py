"""EarnEvent dataclass round-trip and helper tests."""
from __future__ import annotations

from defi_investor.models import (
    EarnEvent,
    SCRAPER_VERSION,
    _epoch_ms_to_iso,
    coin_to_symbol,
    parse_apy,
    parse_max_step,
)


def test_epoch_ms_to_iso_lab():
    # LAB startTime observed on 2026-07-09 probe
    assert _epoch_ms_to_iso(1778572485770) == "2026-05-12T07:54:45.770000+00:00"


def test_epoch_ms_to_iso_none():
    assert _epoch_ms_to_iso(None) is None


def test_parse_apy_string():
    assert parse_apy("365.00") == 365.0


def test_parse_apy_empty():
    assert parse_apy("") is None
    assert parse_apy(None) is None


def test_parse_apy_garbage():
    assert parse_apy("not a number") is None


def test_parse_max_step_lab_shape():
    apy_list = [
        {"apy": "365.00", "maxStepValue": "1000.00000000", "minStepValue": "0.00", "productId": "x"}
    ]
    assert parse_max_step(apy_list) == 1000.0


def test_parse_max_step_empty():
    assert parse_max_step(None) is None
    assert parse_max_step([]) is None
    assert parse_max_step("not a list") is None


def test_coin_to_symbol():
    assert coin_to_symbol("LAB") == "LABUSDT"
    assert coin_to_symbol("btc") == "BTCUSDT"


def test_earn_event_roundtrip():
    ev = EarnEvent(
        product_id="1438002720001814528",
        coin_name="LAB",
        second_biz_line="Savings",
        max_apy=365.0,
        min_apy=365.0,
        per_user_cap_underlying=1000.0,
        tiers=[{"apy": "365.00", "maxStepValue": "1000.00000000",
                "minStepValue": "0.00000000", "rateLevel": 0}],
        start_time="2026-05-12T07:54:45.770000+00:00",
        status=6,
        sold_out=True,
    )
    d = ev.to_dict()
    ev2 = EarnEvent.from_dict(d)
    assert ev2 == ev


def test_earn_event_from_dict_ignores_unknown_keys():
    d = {
        "product_id": "abc",
        "coin_name": "FOO",
        "second_biz_line": "Savings",
        "unknown_future_field": "hi",
    }
    ev = EarnEvent.from_dict(d)
    assert ev.product_id == "abc"
    assert ev.scraper_version == SCRAPER_VERSION  # default filled


def test_earn_event_from_dict_defaults_tiers_when_missing():
    """Old JSONL rows (pre-0.2.0) have no tiers key; must load as []."""
    d = {
        "product_id": "legacy",
        "coin_name": "OLD",
        "second_biz_line": "Savings",
    }
    ev = EarnEvent.from_dict(d)
    assert ev.tiers == []


def test_earn_event_roundtrip_multi_tier():
    """USDT-shape ladder must survive to_dict / from_dict."""
    tiers = [
        {"apy": "6.16", "maxStepValue": "300.00000000",
         "minStepValue": "0.00000000", "productId": "x", "rateLevel": 0},
        {"apy": "1.50", "maxStepValue": "120000000.00000000",
         "minStepValue": "300.00000000", "productId": "x", "rateLevel": 1},
    ]
    ev = EarnEvent(
        product_id="x",
        coin_name="USDT",
        second_biz_line="Savings",
        max_apy=6.16,
        min_apy=1.50,
        tiers=tiers,
    )
    ev2 = EarnEvent.from_dict(ev.to_dict())
    assert ev2.tiers == tiers
