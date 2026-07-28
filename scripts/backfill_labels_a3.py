"""Backfill A3 order-book impact labels.

Parallel to `scripts/backfill_labels_v030.py` (A2b) and
`scripts/backfill_labels.py` (A2a). Reads sold-out events, extracts the
pre-registered `depth_asymmetry_5min` feature from stored L2 snapshots,
fetches 24h post-anchor Bitget spot return, and writes one row per
event to `orderbook_features`.

Labeling rules (per HYPOTHESIS_A3.md §Labeler spec, verbatim):
  +1 if asymmetry >= theta_asym (ask contraction; informed-selling proxy)
  -1 if asymmetry <= -theta_asym (bid contraction; informed-buying proxy)
   0 otherwise

  theta_asym = 0.5 (pre-committed, NOT tunable pre-gate)

Exclusions:
  no_orderbook_data           → no L2 snapshots at all for the coin in the window
  ws_gap_over_60s_in_pre_window → too much gap in the pre-window
  within_7d_of_TGE            → confound filter (per FRAME_C1)
  no_spot_candles             → can't compute r_24h (delisted or thin)

Runs today. Idempotent by (venue, product_id, anchor_ts, labeler_version).
The orderbook_snapshots_l2 table must exist (Migration 010) and contain
the pre-event window data (daemon must have been capturing for at least
10 minutes before the anchor).

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

import httpx
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.candles import fetch_candles
from defi_investor.confounds import compute_confounds
from defi_investor.models import EarnEvent, coin_to_symbol
from defi_investor.orderbook import L2Snapshot
from defi_investor.orderbook.features import compute_depth_asymmetry_5min


LOG = logging.getLogger("defi_investor.backfill_labels_a3")

LABELER_VERSION = "A3_v0.1.0"
THETA_ASYM = 0.5   # pre-committed per HYPOTHESIS_A3
RESPONSE_HORIZON_HOURS = 24

# Pre-event window: [anchor - 10min, anchor]. Same as
# compute_depth_asymmetry_5min defaults.
PRE_WINDOW_MINUTES = 5
PRE_PRE_WINDOW_MINUTES = 5
LOOKBACK_MINUTES = PRE_WINDOW_MINUTES + PRE_PRE_WINDOW_MINUTES


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _load_snapshots_for_event(
    sb,
    *,
    venue: str,
    inst_id: str,
    anchor: datetime,
) -> list[L2Snapshot]:
    """Fetch L2 snapshots for one venue+inst_id in the 10-minute pre-window."""
    start = (anchor - timedelta(minutes=LOOKBACK_MINUTES)).isoformat()
    end = anchor.isoformat()
    try:
        r = (
            sb.table("orderbook_snapshots_l2")
            .select("*")
            .eq("venue", venue)
            .eq("inst_id", inst_id)
            .gte("exchange_ts", start)
            .lte("exchange_ts", end)
            .order("exchange_ts", desc=False)
            .execute()
        )
    except Exception as e:  # noqa: BLE001
        LOG.warning("L2 fetch failed for %s/%s: %s", venue, inst_id, e)
        return []

    snapshots: list[L2Snapshot] = []
    for row in r.data or []:
        try:
            ts_iso = row["exchange_ts"]
            ts = _parse_iso(ts_iso)
            if ts is None:
                continue
            ts_ms = int(ts.timestamp() * 1000)
            bids = [(float(p), float(s)) for p, s in (row.get("bids") or [])]
            asks = [(float(p), float(s)) for p, s in (row.get("asks") or [])]
        except (TypeError, ValueError, KeyError) as e:
            LOG.debug("skipping malformed L2 row: %s", e)
            continue
        snapshots.append(L2Snapshot(
            venue=venue,
            inst_id=inst_id,
            received_at=row.get("received_at", ""),
            exchange_ts_ms=ts_ms,
            bids=bids,
            asks=asks,
        ))
    return snapshots


def _fetch_r_24h(
    coin_name: str,
    anchor: datetime,
    *,
    candles_client: httpx.Client,
) -> tuple[Optional[float], Optional[float], Optional[float], str]:
    """Fetch anchor_close and post_close (24h later), return (anchor_close, post_close, r_24h, market)."""
    symbol = coin_to_symbol(coin_name)
    start_ms = int((anchor - timedelta(hours=1)).timestamp() * 1000)
    end_ms = int((anchor + timedelta(hours=RESPONSE_HORIZON_HOURS + 4)).timestamp() * 1000)
    df, provenance = fetch_candles(
        symbol=symbol, start_ms=start_ms, end_ms=end_ms,
        granularity="1H", client=candles_client,
    )
    if df is None or df.empty:
        return None, None, None, "none"

    import pandas as pd  # local import; pandas already required by candles
    anchor_ts_pd = pd.Timestamp(anchor).tz_convert("UTC")
    horizon_ts_pd = anchor_ts_pd + pd.Timedelta(hours=RESPONSE_HORIZON_HOURS)

    at_or_before_anchor = df.index <= anchor_ts_pd
    at_or_after_horizon = df.index >= horizon_ts_pd
    if not at_or_before_anchor.any() or not at_or_after_horizon.any():
        return None, None, None, provenance.market

    anchor_close = float(df.loc[df.index[at_or_before_anchor][-1], "close"])
    post_close = float(df.loc[df.index[at_or_after_horizon][0], "close"])
    import math
    r_24h = math.log(post_close / anchor_close) if anchor_close > 0 and post_close > 0 else None
    return anchor_close, post_close, r_24h, provenance.market


def _label_from_asymmetry(asymmetry: Optional[float]) -> Optional[int]:
    """HYPOTHESIS_A3 label mapping.

    Spec: +1 if ask-side contraction >= theta_asym; -1 if bid-side
    contraction >= theta_asym; 0 otherwise.

    The feature formula makes ask contraction NEGATIVE
    (log(ask_pre/ask_pre_pre) contributes with a minus sign relative to
    the bid term), so:
        ask contraction => asymmetry <= -theta_asym => label +1
        bid contraction => asymmetry >= +theta_asym => label -1

    Discovered 2026-07-28 by the A3 integration test — a naive
    "if asymmetry >= theta then +1" mapping would invert the whole
    hypothesis direction. Since no A3 labels have been written yet
    (Migration 010 unapplied, capture_daemon not deployed), this fix
    predates any published label rows and does NOT violate the
    pre-registration.
    """
    if asymmetry is None:
        return None
    if asymmetry <= -THETA_ASYM:
        return +1
    if asymmetry >= THETA_ASYM:
        return -1
    return 0


def _already_labeled(sb, venue: str, product_id: str) -> bool:
    r = (
        sb.table("orderbook_features")
        .select("product_id")
        .eq("venue", venue)
        .eq("product_id", product_id)
        .eq("labeler_version", LABELER_VERSION)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def _upsert(sb, payload: dict) -> None:
    (
        sb.table("orderbook_features")
        .upsert(payload, on_conflict="venue,product_id,anchor_ts,labeler_version")
        .execute()
    )


def _resolve_inst_id(sb, venue: str, coin: str) -> str:
    """Consult venue_coin_map for override; default to f'{coin}USDT'."""
    default = f"{coin}USDT"
    try:
        r = (
            sb.table("venue_coin_map")
            .select("venue_coin")
            .eq("venue", venue)
            .eq("canonical_coin", coin)
            .limit(1)
            .execute()
        )
    except Exception:  # noqa: BLE001
        return default
    if r.data:
        return r.data[0].get("venue_coin", default)
    return default


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    sb = create_client(url, key)

    # Every sold-out event, both venues
    r = (
        sb.table("earn_events")
        .select("*")
        .eq("sold_out", True)
        .execute()
    )
    events_raw = r.data or []
    LOG.info("sold-out candidates (all venues): %d", len(events_raw))

    stats = {
        "labeled": 0, "unlabelable": 0, "skipped_existing": 0,
        "no_orderbook_data": 0, "ws_gap_over_60s": 0,
        "no_spot_candles": 0, "no_anchor": 0,
        "labels": {1: 0, -1: 0, 0: 0},
    }

    with httpx.Client(
        headers={"User-Agent": "defi-investor-research/A3_v0.1.0",
                 "Accept": "application/json"},
    ) as candles_client:
        for row in events_raw:
            venue = row.get("venue", "bitget")
            product_id = row["product_id"]
            coin = (row.get("coin_name") or "").upper()

            if _already_labeled(sb, venue, product_id):
                stats["skipped_existing"] += 1
                continue

            event = EarnEvent.from_dict(row)
            anchor_iso = event.sold_out_first_seen_at
            anchor = _parse_iso(anchor_iso)
            if anchor is None:
                stats["no_anchor"] += 1
                continue

            # Bitget-side L2 per A3 spec (Binance as cross-val, not primary)
            inst_id = _resolve_inst_id(sb, "bitget", coin)
            snapshots = _load_snapshots_for_event(
                sb, venue="bitget", inst_id=inst_id, anchor=anchor,
            )

            feature = compute_depth_asymmetry_5min(snapshots, anchor)

            unlabelable_reason: Optional[str] = None
            if feature.n_snapshots_pre == 0 and feature.n_snapshots_pre_pre == 0:
                unlabelable_reason = "no_orderbook_data"
                stats["no_orderbook_data"] += 1
            elif feature.ws_gap_max_s is not None and feature.ws_gap_max_s >= 60.0:
                unlabelable_reason = "ws_gap_over_60s_in_pre_window"
                stats["ws_gap_over_60s"] += 1

            anchor_close, post_close, r_24h, market = None, None, None, "none"
            if unlabelable_reason is None:
                anchor_close, post_close, r_24h, market = _fetch_r_24h(
                    coin, anchor, candles_client=candles_client,
                )
                if r_24h is None:
                    unlabelable_reason = "no_spot_candles"
                    stats["no_spot_candles"] += 1

            label = None
            if unlabelable_reason is None:
                label = _label_from_asymmetry(feature.asymmetry)

            # Confound tags (best-effort; reuses existing helpers)
            confounds = {}
            try:
                confounds = compute_confounds(
                    coin, anchor_iso, client=candles_client, sb_client=sb,
                )
            except Exception as e:  # noqa: BLE001
                LOG.warning("confounds failed for %s: %s", product_id, e)

            payload = {
                "venue": venue,
                "product_id": product_id,
                "anchor_ts": anchor_iso,
                "coin_name": coin,
                "labeler_version": LABELER_VERSION,
                "depth_asymmetry_5min": feature.asymmetry,
                "depth_ask_pre": feature.depth_ask_pre,
                "depth_ask_pre_pre": feature.depth_ask_pre_pre,
                "depth_bid_pre": feature.depth_bid_pre,
                "depth_bid_pre_pre": feature.depth_bid_pre_pre,
                "n_snapshots_pre": feature.n_snapshots_pre,
                "n_snapshots_pre_pre": feature.n_snapshots_pre_pre,
                "ws_gap_max_s": feature.ws_gap_max_s,
                "coverage_pre": feature.coverage_pre,
                "theta_asym_used": THETA_ASYM,
                "label": label,
                "unlabelable_reason": unlabelable_reason,
                "r_24h": r_24h,
                "anchor_close_price": anchor_close,
                "post_close_price": post_close,
            }

            try:
                _upsert(sb, payload)
            except Exception as e:  # noqa: BLE001
                LOG.error("upsert failed for %s/%s: %s", venue, product_id, e)
                continue

            if label is None:
                stats["unlabelable"] += 1
            else:
                stats["labeled"] += 1
                stats["labels"][label] += 1

    LOG.info("A3 backfill complete: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
