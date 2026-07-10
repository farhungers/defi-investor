"""Tests for the feature snapshot."""
from __future__ import annotations

from defi_investor.features import event_features
from defi_investor.models import EarnEvent


def _lab():
    return EarnEvent(
        product_id="p1",
        coin_name="LAB",
        second_biz_line="Savings",
        max_apy=365.0,
        min_apy=365.0,
        per_user_cap_underlying=1000.0,
        tiers=[{"apy": "365", "maxStepValue": "1000", "minStepValue": "0", "rateLevel": 0}],
        start_time="2026-05-01T00:00:00+00:00",
        period_days=None,
        lock_model=False,
        period_type=1,
        status=6,
        sold_out=True,
        sold_out_first_seen_at="2026-05-15T00:00:00+00:00",
    )


def test_event_features_stable_key_set():
    f = event_features(_lab())
    expected = {
        "apr_at_anchor", "min_apy", "tier_count", "is_single_tier", "is_multi_tier",
        "per_user_cap_underlying", "family", "period_days", "lock_model",
        "period_type", "time_to_sold_out_hours", "days_since_start_time",
        "cohort_size", "cohort_n_active", "cohort_n_sold",
        "cohort_distinct_coins", "cohort_median_life_d",
        "prior_earn_events_for_coin", "is_repeat_coin",
    }
    assert set(f.keys()) == expected


def test_repeat_coin_flag_from_prior_count():
    ev = _lab()
    assert event_features(ev, prior_earn_events_for_coin=0)["is_repeat_coin"] is False
    assert event_features(ev, prior_earn_events_for_coin=3)["is_repeat_coin"] is True
    assert event_features(ev, prior_earn_events_for_coin=None)["is_repeat_coin"] is False


def test_time_to_sold_out_from_lab_dates():
    f = event_features(_lab())
    # 14 days between start and sold-out
    assert f["time_to_sold_out_hours"] == 14 * 24
    assert f["days_since_start_time"] == 14.0


def test_tier_indicators():
    ev = _lab()
    f = event_features(ev)
    assert f["tier_count"] == 1
    assert f["is_single_tier"] is True
    assert f["is_multi_tier"] is False

    ev.tiers = [{"apy": "6"}, {"apy": "1.5"}]
    f = event_features(ev)
    assert f["is_multi_tier"] is True


def test_cohort_ctx_merges_when_provided():
    ctx = {"cohort_size": 6, "n_active": 3, "n_sold": 3,
           "distinct_coins": 5, "median_life_d": 42.0}
    f = event_features(_lab(), cohort_ctx=ctx)
    assert f["cohort_size"] == 6
    assert f["cohort_median_life_d"] == 42.0


def test_missing_fields_yield_none_not_key_omission():
    ev = EarnEvent(product_id="x", coin_name="Y", second_biz_line="Savings")
    f = event_features(ev)
    assert f["apr_at_anchor"] is None
    assert f["time_to_sold_out_hours"] is None
    assert "cohort_size" in f
    assert f["cohort_size"] is None
