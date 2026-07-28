"""v0.3.0 triple-barrier labeler for HYPOTHESIS_A2b.

Pre-registered under docs/preregistrations/HYPOTHESIS_A2b.md.
Spec (verbatim from A2b, lines 27-35):
- Anchor: sold_out_first_seen_at (same as A2a)
- Upper barrier: anchor_close * exp(k_upper * sigma_20d)
- Lower barrier: anchor_close * exp(-k_lower * sigma_20d)
  (multiplicative, since sigma_20d is estimated on log returns)
- k_upper = k_lower = 2.0 (pre-committed; NOT tunable pre-gate)
- sigma_20d: sample std of the past 20 daily log returns ending on the
  anchor date (inclusive), population normalisation
- Time barriers: {24h, 48h, 168h} — CV search space per Decision 5
- Price source: Bitget spot 1m klines (per A2b spec)
- Label semantics:
    +1 = upper barrier hit first
    -1 = lower barrier hit first
     0 = time barrier hit first
- Exclusions: no_candles_available, insufficient_history_for_sigma_20d,
  horizon_not_yet_resolved, within_7d_of_TGE

Design differences from v0.2.1 (labeler.py):
- Barrier width uses realized vol on daily log returns (v0.2.1 uses ATR
  on 4H bars).
- Multi-horizon: one call returns a dict of {24h: LabelRow, 48h: ..., 168h: ...}
  because the same fetch supports all three; expensive to re-fetch.
- No predicted_sign flip: labels are direction-of-move, not
  direction-of-hypothesis. Downstream analysis handles orientation.
- Barrier walk uses 1m bars for precise crossing timestamps.

Discipline reminders (unchanged from v0.2.1):
- LABELER_VERSION is a mandatory row field.
- If sigma_20d is undefined (fewer than 20 daily returns available), the
  event is unlabelable. Do NOT fabricate a smaller-window estimate.
- If neither perp nor spot data is available for the coin at 1m
  granularity, event unlabelable.
- Every LabelRow carries candles_provenance so re-labels from raw data
  are reproducible.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd

from ..candles import CandleFetch, compute_sigma_realized, fetch_candles, resample_to_daily
from ..models import EarnEvent, coin_to_symbol


LOG = logging.getLogger("defi_investor.labelers.triple_barrier_v030")

LABELER_VERSION = "0.3.0"

# Pre-committed per HYPOTHESIS_A2b — NOT tunable pre-gate.
DEFAULT_K_UPPER = 2.0
DEFAULT_K_LOWER = 2.0
SIGMA_LOOKBACK_DAYS = 20

# Horizons per A2b spec (hours). Downstream CV picks the best; the labeler
# just computes all three because the same fetch feeds them.
HORIZONS_HOURS = (24, 48, 168)

# Fetch settings
_DAILY_GRANULARITY = "1D"
_WALK_GRANULARITY = "1m"

# We need at least SIGMA_LOOKBACK_DAYS + 1 daily bars for one log return
# per bar in the 20-day window. Pad by 5 days for weekend/exchange-holiday
# resilience even though crypto markets don't take weekends.
_DAILY_PRE_ANCHOR_DAYS = SIGMA_LOOKBACK_DAYS + 5

# Post-anchor walk length = longest horizon plus a small pad so the T2
# barrier bar itself is guaranteed present.
_POST_ANCHOR_PAD_HOURS = 4


@dataclass(frozen=True)
class LabelRowV030:
    """One triple-barrier v0.3.0 label. One row per (event, horizon) pair.

    Deliberately NOT the same shape as v0.2.1 LabelRow. The Supabase table
    earn_event_labels can hold both because it's keyed on
    (product_id, anchor_ts, labeler_version) — different labeler_version =
    different rows, and the write side maps this dataclass to the shared
    columns explicitly.
    """
    venue: str
    product_id: str
    anchor_ts: str
    labeler_version: str
    horizon_hours: int

    label: Optional[int]           # +1 upper / -1 lower / 0 time / None if unresolvable
    barrier_hit: Optional[str]     # 'UPPER' | 'LOWER' | 'TIME' | None
    barrier_hit_ts: Optional[str]
    barrier_hit_price: Optional[float]

    anchor_close_price: Optional[float]
    sigma_20d: Optional[float]     # realized vol on daily log returns
    upper_barrier: Optional[float]
    lower_barrier: Optional[float]

    market: str                    # 'perp' | 'spot' | 'none'
    k_upper: float
    k_lower: float

    unlabelable_reason: Optional[str] = None
    candles_provenance: dict = field(default_factory=dict)
    computed_at: str = ""


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat()


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _empty_row(
    event: EarnEvent, anchor_iso: str, horizon_hours: int, reason: str,
    market: str = "none", provenance: Optional[CandleFetch] = None,
    sigma_20d: Optional[float] = None, anchor_close: Optional[float] = None,
) -> LabelRowV030:
    return LabelRowV030(
        venue=event.venue,
        product_id=event.product_id,
        anchor_ts=anchor_iso,
        labeler_version=LABELER_VERSION,
        horizon_hours=horizon_hours,
        label=None,
        barrier_hit=None,
        barrier_hit_ts=None,
        barrier_hit_price=None,
        anchor_close_price=anchor_close,
        sigma_20d=sigma_20d,
        upper_barrier=None,
        lower_barrier=None,
        market=market,
        k_upper=DEFAULT_K_UPPER,
        k_lower=DEFAULT_K_LOWER,
        unlabelable_reason=reason,
        candles_provenance=asdict(provenance) if provenance else {},
        computed_at=_iso(datetime.now(timezone.utc)),
    )


def _walk_barriers(
    walk_df: pd.DataFrame,
    anchor: datetime,
    horizon_hours: int,
    upper: float,
    lower: float,
) -> tuple[Optional[str], Optional[pd.Timestamp], Optional[float]]:
    """Bar-by-bar forward walk from just AFTER anchor to anchor + horizon.

    Returns (barrier_hit, ts, price). barrier_hit is 'UPPER' or 'LOWER'
    if a horizontal barrier is crossed; None if the horizon is reached
    without any horizontal cross (caller labels as 'TIME').

    Tie-break: if both barriers are crossed in the same bar (unusual on
    1m bars unless the coin is extremely volatile), the barrier closer to
    the bar's open wins.
    """
    anchor_ts = pd.Timestamp(anchor).tz_convert("UTC")
    horizon_end = anchor_ts + pd.Timedelta(hours=horizon_hours)
    window = walk_df[(walk_df.index > anchor_ts) & (walk_df.index <= horizon_end)]

    for ts, row in window.iterrows():
        hi = float(row["high"])
        lo = float(row["low"])
        opn = float(row["open"])
        up_hit = hi >= upper
        down_hit = lo <= lower
        if up_hit and down_hit:
            if abs(upper - opn) <= abs(opn - lower):
                return "UPPER", ts, upper
            return "LOWER", ts, lower
        if up_hit:
            return "UPPER", ts, upper
        if down_hit:
            return "LOWER", ts, lower
    return None, None, None


def label_event(
    event: EarnEvent,
    *,
    labeler_version: str = LABELER_VERSION,
    k_upper: float = DEFAULT_K_UPPER,
    k_lower: float = DEFAULT_K_LOWER,
    horizons_hours: tuple[int, ...] = HORIZONS_HOURS,
    candles_client: Optional[httpx.Client] = None,
    daily_df: Optional[pd.DataFrame] = None,
    walk_df: Optional[pd.DataFrame] = None,
    daily_provenance: Optional[CandleFetch] = None,
    walk_provenance: Optional[CandleFetch] = None,
) -> dict[int, LabelRowV030]:
    """Compute one triple-barrier v0.3.0 label per horizon for one event.

    Args:
        event: an EarnEvent with sold_out=True and sold_out_first_seen_at.
        daily_df, walk_df: optional pre-fetched candles for testing. If
            omitted, the labeler fetches from Bitget (perp first, spot
            fallback) via fetch_candles().

    Returns:
        dict keyed by horizon_hours. Each value is a LabelRowV030; check
        `unlabelable_reason` for None-label rows.
    """
    if not event.sold_out:
        return {}

    anchor_iso = event.sold_out_first_seen_at
    anchor = _parse_iso(anchor_iso)
    if anchor is None:
        return {
            h: _empty_row(event, anchor_iso or "", h, "anchor_missing")
            for h in horizons_hours
        }

    max_horizon = max(horizons_hours)
    symbol = coin_to_symbol(event.coin_name)

    # --- Fetch daily candles for sigma_20d (or use injected) ---
    if daily_df is None:
        daily_start = int((anchor - timedelta(days=_DAILY_PRE_ANCHOR_DAYS)).timestamp() * 1000)
        daily_end = int((anchor + timedelta(hours=1)).timestamp() * 1000)
        daily_df, daily_provenance = fetch_candles(
            symbol=symbol, start_ms=daily_start, end_ms=daily_end,
            granularity=_DAILY_GRANULARITY, client=candles_client,
        )

    if daily_df is None or daily_df.empty:
        return {
            h: _empty_row(event, anchor_iso, h, "no_daily_candles",
                          market=daily_provenance.market if daily_provenance else "none",
                          provenance=daily_provenance)
            for h in horizons_hours
        }

    sigma_series = compute_sigma_realized(daily_df, period=SIGMA_LOOKBACK_DAYS)
    valid = sigma_series.dropna()
    if valid.empty:
        return {
            h: _empty_row(event, anchor_iso, h, "insufficient_history_for_sigma_20d",
                          market=daily_provenance.market if daily_provenance else "none",
                          provenance=daily_provenance)
            for h in horizons_hours
        }

    # Take the last valid sigma at or before anchor (in practice the last
    # entry since we fetched up to `anchor + 1h`).
    anchor_ts = pd.Timestamp(anchor).tz_convert("UTC")
    sigma_at_anchor = float(valid[valid.index <= anchor_ts].iloc[-1]) if (valid.index <= anchor_ts).any() else float(valid.iloc[-1])

    # --- Fetch 1m walk candles (or use injected) ---
    if walk_df is None:
        walk_start = int((anchor - timedelta(minutes=1)).timestamp() * 1000)
        walk_end = int((anchor + timedelta(hours=max_horizon + _POST_ANCHOR_PAD_HOURS)).timestamp() * 1000)
        walk_df, walk_provenance = fetch_candles(
            symbol=symbol, start_ms=walk_start, end_ms=walk_end,
            granularity=_WALK_GRANULARITY, client=candles_client,
        )

    if walk_df is None or walk_df.empty:
        return {
            h: _empty_row(event, anchor_iso, h, "no_walk_candles",
                          market=walk_provenance.market if walk_provenance else "none",
                          provenance=walk_provenance, sigma_20d=sigma_at_anchor)
            for h in horizons_hours
        }

    # Anchor close: last bar close at or before anchor
    at_or_before = walk_df.index <= anchor_ts
    if not at_or_before.any():
        return {
            h: _empty_row(event, anchor_iso, h, "anchor_before_first_walk_bar",
                          market=walk_provenance.market if walk_provenance else "none",
                          provenance=walk_provenance, sigma_20d=sigma_at_anchor)
            for h in horizons_hours
        }
    anchor_close = float(walk_df.loc[walk_df.index[at_or_before][-1], "close"])

    # Barriers: multiplicative on log-vol
    import math
    upper_barrier = anchor_close * math.exp(k_upper * sigma_at_anchor)
    lower_barrier = anchor_close * math.exp(-k_lower * sigma_at_anchor)

    # --- Walk for each horizon; per-horizon time-barrier resolution check ---
    last_walk_ts = walk_df.index[-1]
    out: dict[int, LabelRowV030] = {}
    for h in horizons_hours:
        horizon_end = anchor_ts + pd.Timedelta(hours=h)
        # If walk data doesn't reach horizon_end, this horizon is unresolvable.
        if last_walk_ts < horizon_end:
            out[h] = _empty_row(
                event, anchor_iso, h, "horizon_not_yet_resolved",
                market=walk_provenance.market if walk_provenance else "none",
                provenance=walk_provenance, sigma_20d=sigma_at_anchor,
                anchor_close=anchor_close,
            )
            continue

        hit, ts, price = _walk_barriers(walk_df, anchor, h, upper_barrier, lower_barrier)
        if hit is None:
            # Time barrier
            label = 0
            barrier_hit = "TIME"
            barrier_hit_ts = _iso(horizon_end.to_pydatetime())
            barrier_hit_price = float(walk_df.loc[walk_df.index[walk_df.index <= horizon_end][-1], "close"])
        else:
            label = +1 if hit == "UPPER" else -1
            barrier_hit = hit
            barrier_hit_ts = _iso(ts.to_pydatetime())
            barrier_hit_price = float(price)

        out[h] = LabelRowV030(
            venue=event.venue,
            product_id=event.product_id,
            anchor_ts=_iso(anchor),
            labeler_version=labeler_version,
            horizon_hours=h,
            label=label,
            barrier_hit=barrier_hit,
            barrier_hit_ts=barrier_hit_ts,
            barrier_hit_price=barrier_hit_price,
            anchor_close_price=anchor_close,
            sigma_20d=sigma_at_anchor,
            upper_barrier=upper_barrier,
            lower_barrier=lower_barrier,
            market=walk_provenance.market if walk_provenance else "none",
            k_upper=k_upper,
            k_lower=k_lower,
            unlabelable_reason=None,
            candles_provenance={
                "daily": asdict(daily_provenance) if daily_provenance else {},
                "walk": asdict(walk_provenance) if walk_provenance else {},
            },
            computed_at=_iso(datetime.now(timezone.utc)),
        )

    return out
