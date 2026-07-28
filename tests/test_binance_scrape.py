"""Tests for the Binance scrape merge + disappearance logic."""
from __future__ import annotations

from defi_investor.binance_scrape import merge_binance_events
from defi_investor.models import EarnEvent


def _mk(pid: str, sold_out: bool = False, **kw) -> EarnEvent:
    return EarnEvent(
        product_id=pid,
        coin_name=kw.get("coin_name", pid.rstrip("0123456789") or "X"),
        second_biz_line="LENDING_FLEXIBLE",
        venue="binance",
        max_apy=kw.get("max_apy", 5.0),
        sold_out=sold_out,
    )


def test_all_new_products_become_new_events():
    existing = {}
    fresh = [_mk("A001"), _mk("B002")]
    merged, new, upd, gone = merge_binance_events(
        existing, fresh, scraped_at="2026-07-28T15:00:00+00:00",
        raw_capture_path="p", raw_capture_sha256="s",
    )
    assert len(merged) == 2
    assert {e.product_id for e in new} == {"A001", "B002"}
    assert upd == 0
    assert gone == []
    for ev in new:
        assert ev.first_seen_at == "2026-07-28T15:00:00+00:00"


def test_disappearance_flips_prior_to_sold_out():
    prior = _mk("A001")
    prior.first_seen_at = "2026-07-27T00:00:00+00:00"
    prior.last_seen_at = "2026-07-28T14:00:00+00:00"
    existing = {"A001": prior}
    # Fresh scrape returns something different — A001 is gone
    fresh = [_mk("B002")]

    merged, new, upd, gone = merge_binance_events(
        existing, fresh, scraped_at="2026-07-28T15:00:00+00:00",
        raw_capture_path="p", raw_capture_sha256="s",
    )
    assert gone == ["A001"]
    assert merged["A001"].sold_out is True
    assert merged["A001"].sold_out_first_seen_at == "2026-07-28T15:00:00+00:00"
    assert merged["A001"].status == 6
    # First-seen preserved
    assert merged["A001"].first_seen_at == "2026-07-27T00:00:00+00:00"
    # B002 added
    assert "B002" in merged
    assert len(new) == 1


def test_already_sold_out_not_re_disappeared():
    prior = _mk("A001", sold_out=True)
    prior.first_seen_at = "2026-07-27T00:00:00+00:00"
    prior.sold_out_first_seen_at = "2026-07-27T12:00:00+00:00"
    existing = {"A001": prior}
    fresh = []  # A001 still absent

    _, _, _, gone = merge_binance_events(
        existing, fresh, scraped_at="2026-07-28T15:00:00+00:00",
        raw_capture_path="p", raw_capture_sha256="s",
    )
    assert gone == []  # already sold-out, don't fire twice


def test_updated_events_preserve_first_seen():
    prior = _mk("A001")
    prior.first_seen_at = "2026-07-27T00:00:00+00:00"
    existing = {"A001": prior}
    fresh = [_mk("A001", max_apy=7.0)]

    merged, new, upd, gone = merge_binance_events(
        existing, fresh, scraped_at="2026-07-28T15:00:00+00:00",
        raw_capture_path="p", raw_capture_sha256="s",
    )
    assert new == []
    assert upd == 1
    assert gone == []
    assert merged["A001"].first_seen_at == "2026-07-27T00:00:00+00:00"
    assert merged["A001"].last_seen_at == "2026-07-28T15:00:00+00:00"
    assert merged["A001"].max_apy == 7.0


def test_reappearance_does_not_reset_sold_out_flag_if_prior_was_sold_out():
    # Rare but possible: a product marked sold_out earlier reappears in the
    # feed. Current policy: it comes back in as a new observation (sold_out
    # follows the fresh event's value). The reopen semantics would be added
    # separately if we decide to model it.
    prior = _mk("A001", sold_out=True)
    prior.sold_out_first_seen_at = "2026-07-27T12:00:00+00:00"
    prior.first_seen_at = "2026-07-27T00:00:00+00:00"
    existing = {"A001": prior}
    fresh = [_mk("A001", sold_out=False)]  # back in the feed, not marked sold_out

    merged, new, upd, gone = merge_binance_events(
        existing, fresh, scraped_at="2026-07-28T15:00:00+00:00",
        raw_capture_path="p", raw_capture_sha256="s",
    )
    assert gone == []
    assert new == []
    assert upd == 1
    # first_seen preserved; sold_out reflects fresh row (False); sold_out_first_seen_at kept
    assert merged["A001"].first_seen_at == "2026-07-27T00:00:00+00:00"
    assert merged["A001"].sold_out is False
    assert merged["A001"].sold_out_first_seen_at == "2026-07-27T12:00:00+00:00"
