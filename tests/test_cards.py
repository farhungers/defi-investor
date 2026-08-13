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


OBSERVED_AT = "2026-07-10T02:35:00+00:00"


def _ev(
    *,
    coin: str = "LAB",
    apy: float = 365.0,
    tiers: list[dict] | None = None,
    cap: float = 1000.0,
    product_id: str = "1438002720001814528",
    status: int = 6,
    sold_out: bool = True,
    start: str = "2026-05-12T07:54:45.770000+00:00",
    biz: str = "Savings",
) -> EarnEvent:
    if tiers is None:
        tiers = [{
            "apy": f"{apy:.2f}", "maxStepValue": f"{cap:.2f}",
            "minStepValue": "0", "productId": product_id, "rateLevel": 0,
        }]
    return EarnEvent(
        product_id=product_id, coin_name=coin, second_biz_line=biz,
        max_apy=apy, min_apy=apy, per_user_cap_underlying=cap,
        tiers=tiers, start_time=start, status=status, sold_out=sold_out,
    )


def _usdt_tiered() -> EarnEvent:
    pid = "964334561256718336"
    return _ev(
        coin="USDT", apy=6.16, cap=300.0, product_id=pid,
        status=2, sold_out=False, start="2025-01-15T00:00:00+00:00",
        tiers=[
            {"apy": "6.16", "maxStepValue": "300", "minStepValue": "0",
             "productId": pid, "rateLevel": 0},
            {"apy": "1.50", "maxStepValue": "120000000", "minStepValue": "300",
             "productId": pid, "rateLevel": 1},
        ],
    )


def _assert_contains(text: str, *fragments: str) -> None:
    """Assert each fragment appears; failure message names the missing one."""
    for f in fragments:
        assert f in text, f"missing fragment: {f!r}"


def test_sold_out_card_lab_shape():
    c = sold_out_card(_ev(), observed_at=OBSERVED_AT)
    _assert_contains(
        c,
        "SOLD OUT", "LAB", "Savings", "365%", "1,000 LAB", "single-tier",
        "1438002720001814528", "<b>", "</b>", "<pre>",
        "STRUCTURE", "TIMING", "WHY THIS IS INTERESTING",
    )


def test_sold_out_card_stars_for_high_apr():
    # LAB 365% APR — top-tier rarity == 5 stars
    assert "★★★★★" in sold_out_card(_ev(), observed_at=OBSERVED_AT)


def test_reopened_card_uses_green_marker():
    c = reopened_card(_ev(), observed_at=OBSERVED_AT)
    # always 4 stars for a re-open
    _assert_contains(c, "🟢", "RE-OPENED", "1438002720001814528", "★★★★☆")


def test_new_listing_card_multi_tier_summary():
    c = new_listing_card(_usdt_tiered(), observed_at=OBSERVED_AT)
    _assert_contains(
        c,
        "NEW LISTING", "USDT",
        "6.16%", "1.50%", "2-tier",
        "TIER LADDER", "L0", "L1",
    )


def test_stall_card_has_actions_link_when_url_given():
    c = stall_card(
        last_scrape_at="2026-07-10T01:30:00+00:00",
        minutes_ago=42, threshold_min=30,
        actions_url="https://github.com/farhungers/defi-investor/actions",
    )
    _assert_contains(
        c, "SCRAPER STALL", "42m ago", "farhungers/defi-investor",
        '<a href=', "WHAT TO CHECK",
    )


def test_stall_card_no_link_when_url_absent():
    c = stall_card(
        last_scrape_at="2026-07-10T01:30:00+00:00",
        minutes_ago=42, threshold_min=30,
    )
    assert '<a href' not in c


def test_parser_drift_card_lists_coins():
    c = parser_drift_card(
        coin_names=["ABC", "DEF", "GHI"], drift_count=3,
        observed_at=OBSERVED_AT,
    )
    _assert_contains(c, "PARSER DRIFT", "3", "ABC", "DEF", "WHAT THIS MEANS")


def test_sold_out_card_cohort_section_toggles_on_ctx():
    ctx = {
        "cohort_size": 6, "n_active": 3, "n_sold": 3,
        "median_life_d": 42.0, "this_life_d": 58.0,
        "band_lo": 357.7, "band_hi": 372.3, "distinct_coins": 5,
    }
    with_ctx = sold_out_card(_ev(), observed_at=OBSERVED_AT, ctx=ctx)
    without_ctx = sold_out_card(_ev(), observed_at=OBSERVED_AT, ctx=None)
    _assert_contains(with_ctx, "COHORT", "6 rows", "42")
    assert "COHORT" not in without_ctx


def test_parser_drift_card_truncates_long_coin_list():
    coins = [f"C{i}" for i in range(20)]
    c = parser_drift_card(
        coin_names=coins, drift_count=20, observed_at=OBSERVED_AT,
    )
    assert "…" in c


def test_card_escapes_untrusted_coin_name():
    """A malicious coin_name shouldn't inject HTML."""
    c = sold_out_card(_ev(coin="<script>x</script>"), observed_at=OBSERVED_AT)
    assert "<script>x</script>" not in c
    assert "&lt;script&gt;" in c
