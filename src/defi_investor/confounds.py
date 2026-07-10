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
  open interest but no historical endpoint. For events already resolved
  this value is unrecoverable. Forward-collect by adding an OI snapshot
  step to the 15-min scraper cron and re-labeling from that data once
  it accumulates.
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
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx

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


def compute_confounds(
    coin_name: str,
    anchor_iso: str,
    *,
    client: Optional[httpx.Client] = None,
) -> dict:
    """One-shot: return a dict of all backfill-computable confound tags.

    Missing values remain None so downstream storage stays schema-stable.
    """
    try:
        anchor = datetime.fromisoformat(anchor_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return {
            "bitget_listing_age_days": None,
            "within_7d_of_tge": None,
            "btc_ret_7d_prior": None,
            "perp_vol_change_prior_24h": None,
        }

    age = listing_age_days(coin_name, anchor, client=client)
    within_7 = (age is not None and age < 7)
    btc7 = btc_return(anchor - timedelta(days=7), anchor, client=client)
    vol24 = perp_vol_change_prior_24h(coin_name, anchor, client=client)
    return {
        "bitget_listing_age_days": age,
        "within_7d_of_tge": within_7 if age is not None else None,
        "btc_ret_7d_prior": btc7,
        "perp_vol_change_prior_24h": vol24,
    }
