"""Feature snapshot at the label anchor (PHASE_2_PLAN §4).

One `event_features(event, cohort_ctx=None) -> dict` call per event. The
dict is JSON-safe and lands in `earn_event_labels.features` for downstream
Phase 3 to slice into a feature matrix.

Discipline reminders:

- No features that read price AFTER the anchor. The label already consumes
  post-anchor price; a feature that also reads it is a look-ahead trap.
- Features that need external data (TOTAL3 change, OI delta) live in a
  separate `confound_tags(...)` call so the boundary between "predictors"
  and "controls" is explicit.
- Every feature is either present with a value OR present with None. No
  key omission — the Phase 3 matrix relies on stable columns.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from .models import EarnEvent


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _delta_hours(a: Optional[str], b: Optional[str]) -> Optional[float]:
    da, db = _parse_iso(a), _parse_iso(b)
    if da is None or db is None:
        return None
    return (db - da).total_seconds() / 3600.0


def event_features(event: EarnEvent,
                   cohort_ctx: Optional[dict] = None,
                   *,
                   prior_earn_events_for_coin: Optional[int] = None) -> dict:
    """Return a JSON-safe dict of features known at the anchor.

    Args:
        event: sold-out (or resolved) EarnEvent.
        cohort_ctx: optional dict from `defi_investor.context.cohort_context`
            keyed on the same event. If None, cohort features are None.
        prior_earn_events_for_coin: count of Earn events observed for this
            coin BEFORE the current event. None if not yet computed.

    Returns:
        Dict with a stable key set. Feature values may be None when the
        underlying data isn't present, but every key is emitted.
    """
    time_to_sold_hours = _delta_hours(
        event.start_time, event.sold_out_first_seen_at,
    )
    days_since_start = (
        time_to_sold_hours / 24.0 if time_to_sold_hours is not None else None
    )
    tier_count = len(event.tiers or [])
    if cohort_ctx is None:
        cohort_ctx = {}
    return {
        "apr_at_anchor": event.max_apy,
        "min_apy": event.min_apy,
        "tier_count": tier_count,
        "is_single_tier": tier_count == 1,
        "is_multi_tier": tier_count >= 2,
        "per_user_cap_underlying": event.per_user_cap_underlying,
        "family": event.second_biz_line,
        "period_days": event.period_days,
        "lock_model": event.lock_model,
        "period_type": event.period_type,
        "time_to_sold_out_hours": time_to_sold_hours,
        "days_since_start_time": days_since_start,
        "cohort_size": cohort_ctx.get("cohort_size"),
        "cohort_n_active": cohort_ctx.get("n_active"),
        "cohort_n_sold": cohort_ctx.get("n_sold"),
        "cohort_distinct_coins": cohort_ctx.get("distinct_coins"),
        "cohort_median_life_d": cohort_ctx.get("median_life_d"),
        "prior_earn_events_for_coin": prior_earn_events_for_coin,
        "is_repeat_coin": (
            prior_earn_events_for_coin is not None
            and prior_earn_events_for_coin > 0
        ),
    }
