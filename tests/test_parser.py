"""Parser tests using the 2026-07-09 probe fixture.

The fixture is a real Bitget earning page HTML. If Bitget changes their page,
regenerate the fixture and update expected values.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from defi_investor.parsers.next_data import (
    ParseError,
    extract_next_data,
    parse_earning_page,
)


FIXTURE = Path(__file__).parent / "fixtures" / "earning_2026-07-09.html"


@pytest.fixture(scope="module")
def html() -> str:
    return FIXTURE.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def events(html: str):
    return parse_earning_page(html)


def test_extract_next_data_ok(html: str):
    blob = extract_next_data(html)
    assert "props" in blob
    assert "pageProps" in blob["props"]


def test_extract_next_data_missing():
    with pytest.raises(ParseError):
        extract_next_data("<html><body>no script tag</body></html>")


def test_extract_next_data_bad_json():
    bad = '<script id="__NEXT_DATA__" type="application/json">{not json</script>'
    with pytest.raises(ParseError):
        extract_next_data(bad)


def test_parse_earning_page_returns_events(events):
    assert len(events) > 100
    # All events must have identity fields
    for ev in events:
        assert ev.product_id
        assert ev.coin_name
        assert ev.second_biz_line


def test_parse_earning_page_finds_lab(events):
    lab = [e for e in events if e.coin_name == "LAB"]
    assert len(lab) == 1
    ev = lab[0]
    assert ev.product_id == "1438002720001814528"
    assert ev.second_biz_line == "Savings"
    assert ev.max_apy == 365.0
    assert ev.min_apy == 365.0
    assert ev.per_user_cap_underlying == 1000.0
    assert ev.status == 6
    assert ev.sold_out is True
    assert ev.start_time == "2026-05-12T07:54:45.770000+00:00"
    assert ev.data_quality == "complete"


def test_parse_earning_page_dedupes_by_product_id(events):
    ids = [e.product_id for e in events]
    assert len(ids) == len(set(ids))


def test_parse_earning_page_sold_out_matches_status(events):
    for ev in events:
        if ev.status == 6:
            assert ev.sold_out is True
        elif ev.status is not None and ev.status != 6:
            assert ev.sold_out is False


def test_parse_earning_page_high_apy_cohort_present(events):
    high = [e for e in events if e.max_apy and e.max_apy >= 50.0]
    # Probe log recorded 18 pools at >=50%. Allow drift down to 10.
    assert len(high) >= 10
    # Every high-APR pool in probe was Savings
    for ev in high:
        assert ev.second_biz_line in ("Savings", "PosStaking"), (
            f"unexpected biz line for high APR: {ev.coin_name} {ev.second_biz_line}"
        )


def test_parse_earning_page_all_known_biz_lines(events):
    biz_lines = {e.second_biz_line for e in events}
    # These must be present in a healthy scrape of the earning page
    assert "Savings" in biz_lines
    assert "PosStaking" in biz_lines


def test_parse_earning_page_deterministic(html):
    a = parse_earning_page(html)
    b = parse_earning_page(html)
    assert len(a) == len(b)
    a_map = {e.product_id: e for e in a}
    b_map = {e.product_id: e for e in b}
    assert a_map == b_map


def test_parse_earning_page_preserves_lab_single_tier(events):
    """LAB is a single-tier 365% Savings bait pool."""
    lab = next(e for e in events if e.coin_name == "LAB")
    assert isinstance(lab.tiers, list)
    assert len(lab.tiers) == 1
    t0 = lab.tiers[0]
    assert t0["apy"] == "365.00"
    assert t0["maxStepValue"] == "1000.00000000"
    assert t0["minStepValue"] == "0.00000000"
    assert t0["rateLevel"] == 0


def test_parse_earning_page_preserves_multi_tier_ladder(events):
    """At least one product has a 2+ tier ladder (USDT-shape stablecoin savings)."""
    multi = [e for e in events if len(e.tiers) >= 2]
    assert multi, "expected at least one multi-tier product in the fixture"
    # Every tier has the wire keys we depend on downstream
    for ev in multi:
        levels = [t.get("rateLevel") for t in ev.tiers]
        assert levels == sorted(levels), (
            f"{ev.coin_name} tiers not sorted by rateLevel: {levels}"
        )
        for t in ev.tiers:
            assert set(t.keys()) >= {"apy", "maxStepValue", "minStepValue", "rateLevel"}


def test_parse_earning_page_tier_count_distribution(events):
    """The mix roughly matches probe v2 §5: mostly 1-tier, a handful multi-tier."""
    from collections import Counter
    counts = Counter(len(e.tiers) for e in events)
    # Probe v2 recorded: {0: 33, 1: 359, 2: 8, 3: 2} on 2026-07-09 22:37 UTC
    assert counts.get(1, 0) >= 100
    assert (counts.get(2, 0) + counts.get(3, 0)) >= 1
