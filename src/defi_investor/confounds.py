"""Confound tags computed at label anchor time (METHOD §1).

Populates the confound columns on `earn_event_labels` for the primary
gate's split-analysis (METHOD §2.4 criterion 5).

## What's implemented now

- `listing_age_days`: days between the coin's first Bitget candle and the
  anchor. Feeds `within_7d_of_tge`.
- `btc_return`: BTC USDT-M perp return over an arbitrary window. Used as
  a macro proxy in place of TOTAL3 (see below).
- `perp_vol_change_prior_24h`: previous 24h base-volume vs prior 24h. A
  proxy for coordinated positioning.

## What can't be backfilled now (documented for later)

- `perp_oi_pct_change_prior_24h`: Bitget's V2 public API exposes CURRENT
  open interest but no historical endpoint. Forward-collected by the
  scraper's OI-snapshot step (see `oi_snapshots.py`, migration 005).
  Backfillable for any event whose anchor falls at least 24h after the
  OI cron's first successful snapshot for that coin — anything earlier
  remains None (unrecoverable, tag stays null).
- `total3_pct_change_7d`: CoinGecko free tier gates historical market-cap
  charts behind Pro. As a pragmatic proxy we store `btc_ret_7d_prior`
  computed from Bitget's own BTCUSDT candles. Same macro-direction signal
  in practice for shitcoin cohorts. Switch to true TOTAL3 whenever a paid
  data source is wired.

Provenance: every computed value carries the endpoint and fetch timestamp
in `candles_provenance` on the LabelRow.
"""
from __future__ import annotations

import logging
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
import numpy as np

from .candles import fetch_candles


LOG = logging.getLogger("defi_investor.confounds")

# Bitget caps 1D candle queries at 90 days per request. That's fine for our
# purpose — the primary consumer is `within_7d_of_tge` and the Phase 3
# confound split at `age >= 30d`. Anything older than 90 days is capped and
# returned as `_LISTING_AGE_CAP` so downstream splits still work.
_LISTING_AGE_WINDOW_DAYS = 89   # stay comfortably under the 90-day cap
_LISTING_AGE_CAP = 90           # sentinel: "listed >= 90 days ago"


def listing_age_days(coin_name: str, at_ts: datetime, *,
                     client: Optional[httpx.Client] = None) -> Optional[int]:
    """Days between the coin's earliest Bitget candle in the 90-day window
    preceding `at_ts` and `at_ts` itself.

    Two outcomes worth knowing:

    - Earliest bar strictly inside the window → precise age, in [0, 89].
    - Earliest bar sits at (or before) the window start → coin is ≥ 90 days
      old; we return `_LISTING_AGE_CAP` (=90). The Phase 3 splits only care
      about the >= 30d boundary, so this sentinel is functionally equivalent
      to any larger age.

    Returns None only when neither perp nor spot has any bar in the window.
    """
    symbol = f"{coin_name.upper()}USDT"
    end_ms = int(at_ts.timestamp() * 1000)
    start_ms = int((at_ts - timedelta(days=_LISTING_AGE_WINDOW_DAYS)).timestamp() * 1000)
    df, prov = fetch_candles(
        symbol=symbol,
        start_ms=start_ms,
        end_ms=end_ms,
        granularity="1D",
        client=client,
    )
    if df is None or df.empty:
        LOG.info("listing_age: no candles for %s", symbol)
        return None
    first_ts = df.index[0].to_pydatetime()
    delta_d = (at_ts - first_ts).total_seconds() / 86400.0
    if delta_d >= _LISTING_AGE_WINDOW_DAYS - 0.5:
        return _LISTING_AGE_CAP
    return max(0, int(delta_d))


def btc_return(start_ts: datetime, end_ts: datetime, *,
               client: Optional[httpx.Client] = None) -> Optional[float]:
    """BTCUSDT close-to-close return over the window. None if unavailable.

    Uses 4H bars — matches ATR granularity. Returned as a fraction
    (e.g. -0.12 for a 12% drop).
    """
    start_ms = int(start_ts.timestamp() * 1000)
    end_ms = int(end_ts.timestamp() * 1000)
    df, prov = fetch_candles(
        symbol="BTCUSDT", start_ms=start_ms, end_ms=end_ms,
        granularity="4H", client=client,
    )
    if df is None or df.empty or len(df) < 2:
        return None
    p0 = float(df["close"].iloc[0])
    p1 = float(df["close"].iloc[-1])
    if p0 == 0:
        return None
    return (p1 - p0) / p0


# Annualization for 4H realized vol: 6 bars/day × 365 days = 2190 bars/year.
_BARS_PER_YEAR_4H = 6 * 365


def btc_30d_realized_vol(
    anchor_ts: datetime,
    *,
    client: Optional[httpx.Client] = None,
) -> Optional[float]:
    """Annualized realized volatility of BTCUSDT close-to-close log returns
    over the 30 days preceding `anchor_ts`. METHOD §1.6 regime confound.

    Uses 4H bars → 180 observations per 30d window. Annualized by
    √(bars/year) so downstream buckets read comparably against implied-vol
    conventions (e.g. 0.60 ≈ 60% annualized).

    Returns None when candles are missing or the sample is degenerate
    (< 30 observations, or zero-variance closes).
    """
    end_ms = int(anchor_ts.timestamp() * 1000)
    start_ms = int((anchor_ts - timedelta(days=30)).timestamp() * 1000)
    df, _ = fetch_candles(
        symbol="BTCUSDT", start_ms=start_ms, end_ms=end_ms,
        granularity="4H", client=client,
    )
    if df is None or df.empty or len(df) < 30:
        return None
    closes = df["close"].to_numpy(dtype="float64")
    if not np.all(np.isfinite(closes)) or np.any(closes <= 0):
        return None
    log_r = np.diff(np.log(closes))
    if log_r.size < 2:
        return None
    sample_stdev = float(np.std(log_r, ddof=1))
    if sample_stdev == 0.0:
        return None
    return sample_stdev * math.sqrt(_BARS_PER_YEAR_4H)


def perp_vol_change_prior_24h(coin_name: str, anchor_ts: datetime, *,
                              client: Optional[httpx.Client] = None) -> Optional[float]:
    """Fractional change in 24h base-volume vs the preceding 24h.

    Positive = volume acceleration. Proxy for coordinated positioning.
    Returned as a fraction; None if either window is empty.
    """
    symbol = f"{coin_name.upper()}USDT"
    end = anchor_ts
    mid = anchor_ts - timedelta(hours=24)
    start = anchor_ts - timedelta(hours=48)
    df, _ = fetch_candles(
        symbol=symbol,
        start_ms=int(start.timestamp() * 1000),
        end_ms=int(end.timestamp() * 1000),
        granularity="4H",
        client=client,
    )
    if df is None or df.empty:
        return None
    mid_ts = f"{mid.isoformat()}"
    import pandas as pd
    mid_pd = pd.Timestamp(mid).tz_convert("UTC")
    prior = df[df.index < mid_pd]
    recent = df[df.index >= mid_pd]
    if prior.empty or recent.empty:
        return None
    v_prior = float(prior["base_vol"].sum())
    v_recent = float(recent["base_vol"].sum())
    if v_prior == 0:
        return None
    return (v_recent - v_prior) / v_prior


_OI_SNAPSHOT_MATCH_TOLERANCE = timedelta(minutes=180)
_OI_LOOKUP_WINDOW = timedelta(hours=24) + _OI_SNAPSHOT_MATCH_TOLERANCE

_VEST_WINDOW = timedelta(days=3)
# Widen the query window a bit past the confound window so an anchor
# on the edge still finds a nearby snapshot to consult.
_VEST_SNAPSHOT_LOOKUP_TOLERANCE = timedelta(hours=6)


def perp_oi_pct_change_prior_24h(
    coin_name: str,
    anchor_ts: datetime,
    *,
    sb_client,
) -> Optional[float]:
    """Fractional change in perp OI over the 24h preceding the anchor.

    Reads from `earn_oi_snapshots`, which is populated forward-only by the
    scraper cron. Picks the snapshot closest to `anchor - 24h` and to
    `anchor` itself, each within `_OI_SNAPSHOT_MATCH_TOLERANCE` (180 min,
    ~3x the observed p50 scrape cadence of 60 min; still ≈12% of the 24h
    delta being computed so any matched snapshot is meaningfully close on
    the metric's time scale).

    Returns None when either endpoint has no qualifying snapshot, when the
    coin has no perp market (market='none'), or when the earlier value is
    zero. This is intentional — an unrecoverable tag stays null so the
    Phase 3 confound split treats it as missing rather than as zero-change.
    """
    if sb_client is None:
        return None
    end_ts = anchor_ts + _OI_SNAPSHOT_MATCH_TOLERANCE
    start_ts = anchor_ts - _OI_LOOKUP_WINDOW
    try:
        r = (
            sb_client.table("earn_oi_snapshots")
            .select("snapped_at,market,oi_base")
            .eq("coin_name", coin_name.upper())
            .gte("snapped_at", start_ts.isoformat())
            .lte("snapped_at", end_ts.isoformat())
            .order("snapped_at")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        LOG.warning("oi snapshot query failed for %s: %s", coin_name, e)
        return None

    rows = r.data or []
    perp_rows: list[tuple[datetime, float]] = []
    for row in rows:
        if row.get("market") != "perp":
            continue
        oi = row.get("oi_base")
        if oi is None:
            continue
        try:
            snap_ts = datetime.fromisoformat(str(row["snapped_at"]).replace("Z", "+00:00"))
            oi_f = float(oi)
        except (ValueError, TypeError, KeyError):
            continue
        perp_rows.append((snap_ts, oi_f))
    if not perp_rows:
        return None

    target_before = anchor_ts - timedelta(hours=24)
    before = _pick_closest(perp_rows, target_before, _OI_SNAPSHOT_MATCH_TOLERANCE)
    at = _pick_closest(perp_rows, anchor_ts, _OI_SNAPSHOT_MATCH_TOLERANCE)
    if before is None or at is None:
        return None
    if before == 0:
        return None
    return (at - before) / before


def _pick_closest(
    rows: list[tuple[datetime, float]],
    target: datetime,
    tolerance: timedelta,
) -> Optional[float]:
    best: Optional[tuple[timedelta, float]] = None
    for ts, val in rows:
        delta = ts - target if ts >= target else target - ts
        if delta > tolerance:
            continue
        if best is None or delta < best[0]:
            best = (delta, val)
    return best[1] if best else None


def known_vest_unlock_within_3d(
    coin_name: str,
    anchor_ts: datetime,
    *,
    sb_client,
) -> Optional[bool]:
    """True iff any tracked next_unlock_at falls within ±3d of the anchor.

    Reads from `earn_next_unlocks` populated by the hourly vest scraper.
    Returns:
      - True  : found at least one tracked snapshot whose next_unlock_at
                lies inside [anchor - 3d, anchor + 3d].
      - False : found tracked snapshots for this coin around the anchor
                time, but none had a next_unlock_at in the window.
      - None  : no tracked snapshots for this coin in the query window
                (tokenomist doesn't know this token, or we hadn't started
                snapshotting yet). METHOD §1.2 residual risk.
    """
    if sb_client is None:
        return None
    end_ts = anchor_ts + _VEST_SNAPSHOT_LOOKUP_TOLERANCE
    start_ts = anchor_ts - _VEST_SNAPSHOT_LOOKUP_TOLERANCE
    try:
        r = (
            sb_client.table("earn_next_unlocks")
            .select("snapped_at,status,next_unlock_at")
            .eq("coin_name", coin_name.upper())
            .gte("snapped_at", start_ts.isoformat())
            .lte("snapped_at", end_ts.isoformat())
            .order("snapped_at")
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        LOG.warning("vest snapshot query failed for %s: %s", coin_name, e)
        return None

    rows = r.data or []
    tracked = [row for row in rows if row.get("status") == "tracked_with_unlock"]
    if not tracked:
        return None

    for row in tracked:
        iso = row.get("next_unlock_at")
        if not iso:
            continue
        try:
            unlock_ts = datetime.fromisoformat(str(iso).replace("Z", "+00:00"))
        except ValueError:
            continue
        delta = unlock_ts - anchor_ts if unlock_ts >= anchor_ts else anchor_ts - unlock_ts
        if delta <= _VEST_WINDOW:
            return True
    return False


def compute_confounds(
    coin_name: str,
    anchor_iso: str,
    *,
    client: Optional[httpx.Client] = None,
    sb_client=None,
) -> dict:
    """One-shot: return a dict of all backfill-computable confound tags.

    Missing values remain None so downstream storage stays schema-stable.
    `sb_client` is required only for `perp_oi_pct_change_prior_24h`
    which queries the forward-collected snapshot table; omit it and that
    field stays None.
    """
    empty = {
        "bitget_listing_age_days": None,
        "within_7d_of_tge": None,
        "btc_ret_7d_prior": None,
        "perp_vol_change_prior_24h": None,
        "perp_oi_pct_change_prior_24h": None,
        "known_vest_unlock_within_3d": None,
        "btc_30d_realized_vol": None,
        "btc_ret_30d_prior": None,
    }
    try:
        anchor = datetime.fromisoformat(anchor_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return empty

    age = listing_age_days(coin_name, anchor, client=client)
    within_7 = (age is not None and age < 7)
    btc7 = btc_return(anchor - timedelta(days=7), anchor, client=client)
    btc30 = btc_return(anchor - timedelta(days=30), anchor, client=client)
    rvol30 = btc_30d_realized_vol(anchor, client=client)
    vol24 = perp_vol_change_prior_24h(coin_name, anchor, client=client)
    oi24 = perp_oi_pct_change_prior_24h(coin_name, anchor, sb_client=sb_client) \
        if sb_client is not None else None
    vest3 = known_vest_unlock_within_3d(coin_name, anchor, sb_client=sb_client) \
        if sb_client is not None else None
    return {
        "bitget_listing_age_days": age,
        "within_7d_of_tge": within_7 if age is not None else None,
        "btc_ret_7d_prior": btc7,
        "perp_vol_change_prior_24h": vol24,
        "perp_oi_pct_change_prior_24h": oi24,
        "known_vest_unlock_within_3d": vest3,
        "btc_30d_realized_vol": rvol30,
        "btc_ret_30d_prior": btc30,
    }
