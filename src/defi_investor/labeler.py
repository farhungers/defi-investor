"""Triple-barrier labeler for Earn events (de Prado Ch 3.4, adapted).

Given a sold-out Earn event, this module:

1. Anchors at `sold_out_first_seen_at` (per PHASE_2_PLAN §2). This is our
   observable moment of demand saturation.
2. Fetches Bitget perp (spot fallback) OHLCV for
   `[anchor - warmup_hours, anchor + horizon_days + slack]`.
3. Computes ATR(4H, period=24) up to the anchor bar.
4. Sets three barriers:
     - `T1_UP    = anchor_close + k_up   * ATR_at_anchor`
     - `T1_DOWN  = anchor_close - k_down * ATR_at_anchor`
     - `T2      = anchor_ts     + horizon_days`
5. Walks bar-by-bar from the anchor forward. Records the FIRST barrier hit.

Labels:

    +1  T1_DOWN hit first  (dumped — the H1 sub-hypothesis direction)
    -1  T1_UP   hit first  (pumped — hypothesis wrong for this event)
     0  T2 hits first with no horizontal break

Realized R (per METHOD.md §5.4) is the magnitude of the move normalized to
`k * ATR`, sign-adjusted for the sub-hypothesis direction.

Discipline reminders:

- Labeler version is a mandatory row field. Any parameter change ⇒ bump the
  version. Re-label the whole corpus. Never overwrite in place.
- If ATR is undefined at anchor (insufficient warmup bars), return None.
  Do NOT fabricate a barrier from partial data.
- If neither perp nor spot is available for the coin, return None with an
  `unlabelable_reason`. Excluded from primary per METHOD §5.
- Every LabelRow carries the candle provenance so re-labels from raw data
  are reproducible.
"""
from __future__ import annotations

import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import pandas as pd

from .candles import CandleFetch, compute_atr, fetch_candles
from .models import EarnEvent, coin_to_symbol


LOG = logging.getLogger("defi_investor.labeler")

LABELER_VERSION = "0.2.1"

DEFAULT_HORIZON_DAYS = 7
DEFAULT_K_UP = 2.0
DEFAULT_K_DOWN = 2.0
DEFAULT_ATR_PERIOD = 24
DEFAULT_ATR_GRANULARITY = "4H"
# We fetch a bit extra pre-anchor to warm up ATR and pad post-anchor for T2
_WARMUP_HOURS = 4 * DEFAULT_ATR_PERIOD * 2   # 8 days at 4H bars
_POST_HORIZON_SLACK_HOURS = 8                 # ensure T2 candle is present


@dataclass(frozen=True)
class LabelRow:
    """One triple-barrier label. Mirrors the earn_event_labels table."""
    product_id: str
    anchor_ts: str                        # ISO 8601 UTC
    labeler_version: str
    label: Optional[int]                  # +1 / -1 / 0 / None if unresolved
    realized_r: Optional[float]
    barrier_hit: Optional[str]            # 'T1_UP' | 'T1_DOWN' | 'T2' | None
    barrier_hit_ts: Optional[str]
    anchor_close_price: Optional[float]
    atr_4h_at_anchor: Optional[float]
    market: str                           # 'perp' | 'spot' | 'none'
    horizon_days: int
    k_up: float
    k_down: float
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


def _unlabelable(product_id: str, anchor_ts_iso: str, reason: str,
                 provenance: Optional[CandleFetch] = None,
                 market: str = "none") -> LabelRow:
    return LabelRow(
        product_id=product_id,
        anchor_ts=anchor_ts_iso,
        labeler_version=LABELER_VERSION,
        label=None, realized_r=None,
        barrier_hit=None, barrier_hit_ts=None,
        anchor_close_price=None, atr_4h_at_anchor=None,
        market=market,
        horizon_days=DEFAULT_HORIZON_DAYS,
        k_up=DEFAULT_K_UP, k_down=DEFAULT_K_DOWN,
        unlabelable_reason=reason,
        candles_provenance=asdict(provenance) if provenance else {},
        computed_at=_iso(datetime.now(timezone.utc)),
    )


def _find_anchor_bar(df: pd.DataFrame, anchor: datetime) -> Optional[pd.Timestamp]:
    """Return the timestamp of the last bar that closes AT OR BEFORE the anchor.

    Bitget bar index is bar-OPEN. We use the bar that closes at anchor as the
    reference: its close is the last price known "at the anchor moment" for
    the ATR bar-alignment purpose. In practice with 4H bars this is up to
    4h stale relative to the anchor — accepted per METHOD §5.1 anchor
    precision cap.
    """
    if df.empty:
        return None
    anchor_ts = pd.Timestamp(anchor).tz_convert("UTC")
    # Get the last bar whose index (open) is <= anchor_ts
    mask = df.index <= anchor_ts
    if not mask.any():
        return None
    return df.index[mask][-1]


def _walk_barriers(
    df: pd.DataFrame,
    anchor_ts: pd.Timestamp,
    anchor_close: float,
    up: float,
    down: float,
    horizon_end: pd.Timestamp,
) -> tuple[Optional[str], Optional[pd.Timestamp], Optional[float]]:
    """Bar-by-bar forward walk from just AFTER anchor to horizon_end.

    Returns (barrier_hit, ts, hit_price). Uses bar-high for T1_UP checks and
    bar-low for T1_DOWN checks. Conservative: if both hit in the same bar,
    the closer barrier to the open wins.
    """
    forward = df[(df.index > anchor_ts) & (df.index <= horizon_end)]
    for ts, row in forward.iterrows():
        hi = float(row["high"])
        lo = float(row["low"])
        opn = float(row["open"])
        up_hit = hi >= up
        down_hit = lo <= down
        if up_hit and down_hit:
            # Both barriers crossed in this bar; pick the one closer to open.
            if abs(up - opn) <= abs(opn - down):
                return "T1_UP", ts, up
            return "T1_DOWN", ts, down
        if up_hit:
            return "T1_UP", ts, up
        if down_hit:
            return "T1_DOWN", ts, down
    return None, None, None


def label_event(
    event: EarnEvent,
    *,
    labeler_version: str = LABELER_VERSION,
    horizon_days: int = DEFAULT_HORIZON_DAYS,
    k_up: float = DEFAULT_K_UP,
    k_down: float = DEFAULT_K_DOWN,
    atr_period: int = DEFAULT_ATR_PERIOD,
    atr_granularity: str = DEFAULT_ATR_GRANULARITY,
    predicted_sign: int = +1,
    candles_client: Optional[httpx.Client] = None,
) -> Optional[LabelRow]:
    """Compute a triple-barrier label for one sold-out Earn event.

    Args:
        event: an EarnEvent with sold_out=True and sold_out_first_seen_at set.
        predicted_sign: +1 if the sub-hypothesis predicts a DUMP (H1),
            -1 if it predicts a pump. Sign flips realized_r accordingly.
        (other args map onto the label geometry in PHASE_2_PLAN §3.)

    Returns:
        A LabelRow. `label` may be None if unlabelable — check
        `unlabelable_reason`. Never raises for expected data conditions.
    """
    if not event.sold_out:
        return None
    anchor_iso = event.sold_out_first_seen_at
    anchor = _parse_iso(anchor_iso)
    if anchor is None:
        return _unlabelable(event.product_id, anchor_iso or "",
                            "anchor_missing")

    symbol = coin_to_symbol(event.coin_name)
    start_ms = int((anchor - timedelta(hours=_WARMUP_HOURS)).timestamp() * 1000)
    end_ms = int((anchor + timedelta(days=horizon_days,
                                     hours=_POST_HORIZON_SLACK_HOURS)).timestamp() * 1000)

    df, provenance = fetch_candles(
        symbol=symbol, start_ms=start_ms, end_ms=end_ms,
        granularity=atr_granularity, client=candles_client,
    )
    if df is None or df.empty:
        return _unlabelable(event.product_id, anchor_iso,
                            "no_candles_available", provenance,
                            market=provenance.market)

    anchor_bar_ts = _find_anchor_bar(df, anchor)
    if anchor_bar_ts is None:
        return _unlabelable(event.product_id, anchor_iso,
                            "anchor_before_first_bar", provenance,
                            market=provenance.market)

    atr_series = compute_atr(df, period=atr_period)
    atr_at_anchor = atr_series.get(anchor_bar_ts)
    if pd.isna(atr_at_anchor) or atr_at_anchor is None:
        return _unlabelable(event.product_id, anchor_iso,
                            "atr_undefined_at_anchor", provenance,
                            market=provenance.market)

    anchor_close = float(df.loc[anchor_bar_ts, "close"])
    up_barrier = anchor_close + k_up * float(atr_at_anchor)
    down_barrier = anchor_close - k_down * float(atr_at_anchor)
    horizon_end = anchor_bar_ts + pd.Timedelta(days=horizon_days)

    barrier, ts_hit, price_hit = _walk_barriers(
        df, anchor_bar_ts, anchor_close, up_barrier, down_barrier, horizon_end
    )

    # Compose the label
    if barrier is None:
        # T2 — check if we actually have data through horizon_end
        last_bar_ts = df.index[-1]
        if last_bar_ts < horizon_end:
            return _unlabelable(event.product_id, anchor_iso,
                                "horizon_not_yet_resolved",
                                provenance, market=provenance.market)
        label = 0
        realized_r = 0.0
        barrier_hit_ts = _iso(horizon_end.to_pydatetime())
    else:
        # Sign convention: label = +1 when the direction matches the
        # sub-hypothesis (predicted_sign = +1 => DUMP; so T1_DOWN = +1).
        if barrier == "T1_DOWN":
            label = +1 * predicted_sign
        else:  # T1_UP
            label = -1 * predicted_sign
        # realized_r magnitude in ATR units, sign per hypothesis
        raw_move = (float(price_hit) - anchor_close) / (k_up * float(atr_at_anchor))
        realized_r = -raw_move * predicted_sign   # dump == positive realized_r for H1
        barrier_hit_ts = _iso(ts_hit.to_pydatetime())

    return LabelRow(
        product_id=event.product_id,
        anchor_ts=_iso(anchor),
        labeler_version=labeler_version,
        label=int(label),
        realized_r=float(realized_r),
        barrier_hit=barrier or "T2",
        barrier_hit_ts=barrier_hit_ts,
        anchor_close_price=anchor_close,
        atr_4h_at_anchor=float(atr_at_anchor),
        market=provenance.market,
        horizon_days=horizon_days,
        k_up=k_up,
        k_down=k_down,
        unlabelable_reason=None,
        candles_provenance=asdict(provenance),
        computed_at=_iso(datetime.now(timezone.utc)),
    )
