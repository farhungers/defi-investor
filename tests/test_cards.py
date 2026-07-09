"""Card formatter tests. Verify structure, not exact whitespace."""
from __future__ import annotations

from defi_investor.cards import (
    new_listing_card,
    parser_drift_card,
    reopened_card,
    sold_out_card,
    stall_card,
)
from defi_investor.models import EarnEvent


def _lab() -> EarnEvent:
    return EarnEvent(
        product_id="1438002720001814528",
        coin_name="LAB",
        second_biz_line="Savings",
        max_apy=365.0,
        min_apy=365.0,
        per_user_cap_underlying=1000.0,
        tiers=[{"apy": "365.00", "maxStepValue": "1000.00", "minStepValue": "0",
                "productId": "1438002720001814528", "rateLevel": 0}],
        start_time="2026-05-12T07:54:45.770000+00:00",
        status=6,
        sold_out=True,
    )


def _usdt() -> EarnEvent:
    return EarnEvent(
        product_id="964334561256718336",
        coin_name="USDT",
        second_biz_line="Savings",
        max_apy=6.16,
        min_apy=1.50,
        per_user_cap_underlying=300.0,
        tiers=[
            {"apy": "6.16", "maxStepValue": "300", "minStepValue": "0",
             "productId": "964334561256718336", "rateLevel": 0},
            {"apy": "1.50", "maxStepValue": "120000000", "minStepValue": "300",
             "productId": "964334561256718336", "rateLevel": 1},
        ],
        start_time="2025-01-15T00:00:00+00:00",
        status=2,
        sold_out=False,
    )


def test_sold_out_card_lab_shape():
    c = sold_out_card(_lab(), observed_at="2026-07-10T02:35:00+00:00")
    assert "Sold out" in c
    assert "LAB" in c
    assert "Savings" in c
    assert "365%" in c
    assert "1,000 LAB" in c
    assert "single-tier" in c
    assert "1438002720001814528" in c
    assert "<b>" in c and "</b>" in c
    assert "<pre>" in c


def test_sold_out_card_includes_days_open():
    c = sold_out_card(_lab(), observed_at="2026-07-10T02:35:00+00:00")
    # 2026-05-12 to 2026-07-10 = 58 days
    assert "58d" in c or "59d" in c


def test_reopened_card_uses_green_marker():
    c = reopened_card(_lab(), observed_at="2026-07-10T02:35:00+00:00")
    assert "🟢" in c
    assert "Re-opened" in c
    assert "1438002720001814528" in c


def test_new_listing_card_multi_tier_summary():
    c = new_listing_card(_usdt(), observed_at="2026-07-10T02:35:00+00:00")
    assert "New listing" in c
    assert "USDT" in c
    # multi-tier structure surfaced
    assert "6.16%" in c
    assert "1.50%" in c
    assert "2-tier" in c


def test_stall_card_has_actions_link_when_url_given():
    c = stall_card(
        last_scrape_at="2026-07-10T01:30:00+00:00",
        minutes_ago=42,
        threshold_min=30,
        actions_url="https://github.com/farhungers/defi-investor/actions",
    )
    assert "Scraper stall" in c
    assert "42m ago" in c
    assert "farhungers/defi-investor" in c
    assert '<a href=' in c


def test_stall_card_no_link_when_url_absent():
    c = stall_card(
        last_scrape_at="2026-07-10T01:30:00+00:00",
        minutes_ago=42,
        threshold_min=30,
    )
    assert '<a href' not in c


def test_parser_drift_card_lists_coins():
    c = parser_drift_card(
        coin_names=["ABC", "DEF", "GHI"],
        drift_count=3,
        observed_at="2026-07-10T02:35:00+00:00",
    )
    assert "Parser drift" in c
    assert "3" in c
    assert "ABC" in c
    assert "DEF" in c


def test_parser_drift_card_truncates_long_coin_list():
    coins = [f"C{i}" for i in range(20)]
    c = parser_drift_card(
        coin_names=coins,
        drift_count=20,
        observed_at="2026-07-10T02:35:00+00:00",
    )
    assert "…" in c


def test_card_escapes_untrusted_coin_name():
    """A malicious coin_name shouldn't inject HTML."""
    ev = _lab()
    ev.coin_name = "<script>x</script>"
    c = sold_out_card(ev, observed_at="2026-07-10T02:35:00+00:00")
    assert "<script>x</script>" not in c
    assert "&lt;script&gt;" in c
