"""Placebo cohort backfill for HYPOTHESIS_A2b.

Runs the identical v0.3.0 triple-barrier labeler on synthetic non-event
anchors, per the protocol pre-registered in
`docs/preregistrations/PLACEBO_A2b.md`.

Storage: rows are written with `labeler_version = "0.3.0-placebo#h{H}"`,
distinct from real A2b rows so gate_report_a2b never picks them up.

**Not automated.** Meant to be run once at A2b gate day, with the same
seed each run for reproducibility. Do NOT run before the pre-registration
doc is finalized and its amendment log is stable.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import argparse
import logging
import os
import random
import sys
from datetime import datetime, timedelta, timezone

import httpx
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.candles import fetch_candles
from defi_investor.labelers.triple_barrier_v030 import (
    HORIZONS_HOURS, LABELER_VERSION, label_event,
)
from defi_investor.models import EarnEvent


LOG = logging.getLogger("defi_investor.placebo_backfill_a2b")

# Frozen per PLACEBO_A2b.md — do NOT change without amending the pre-reg
# and discarding prior placebo rows.
PLACEBO_SEED = 20260817
K_PER_EVENT = 20
MIN_PRE_ANCHOR_DAYS = 30      # for sigma_20d
MIN_POST_ANCHOR_HOURS = 168 + 1
MIN_SEPARATION_HOURS = 168    # from any real anchor on same coin


def _placebo_version(horizon_hours: int) -> str:
    return f"{LABELER_VERSION}-placebo#h{horizon_hours}"


def _load_real_anchors(sb) -> dict[str, list[datetime]]:
    """Return {coin_name: [real_anchor_ts, ...]} for exclusion windows."""
    r = sb.table("earn_events").select(
        "coin_name,sold_out_first_seen_at"
    ).not_.is_("sold_out_first_seen_at", "null").execute()
    by_coin: dict[str, list[datetime]] = {}
    for row in r.data or []:
        try:
            ts = datetime.fromisoformat(str(row["sold_out_first_seen_at"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        by_coin.setdefault(row["coin_name"], []).append(ts)
    return by_coin


def _coin_first_bar(coin_name: str, client: httpx.Client) -> datetime | None:
    """Earliest Bitget daily bar for the coin (used to bound sampling window)."""
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    start_ms = int((datetime.now(timezone.utc) - timedelta(days=365)).timestamp() * 1000)
    df, _ = fetch_candles(symbol=f"{coin_name.upper()}USDT",
                         start_ms=start_ms, end_ms=now_ms,
                         granularity="1D", client=client)
    if df is None or df.empty:
        return None
    return df.index[0].to_pydatetime()


def _sample_placebos(
    coin_name: str, real_anchors: list[datetime],
    client: httpx.Client, rng: random.Random,
) -> list[datetime]:
    first_bar = _coin_first_bar(coin_name, client)
    if first_bar is None:
        return []
    window_start = first_bar + timedelta(days=MIN_PRE_ANCHOR_DAYS)
    window_end = datetime.now(timezone.utc) - timedelta(hours=MIN_POST_ANCHOR_HOURS + 1)
    if window_start >= window_end:
        return []

    picks: list[datetime] = []
    attempts = 0
    max_attempts = K_PER_EVENT * 50  # generous
    while len(picks) < K_PER_EVENT and attempts < max_attempts:
        attempts += 1
        span_s = (window_end - window_start).total_seconds()
        t = window_start + timedelta(seconds=rng.random() * span_s)
        if any(abs((t - ra).total_seconds()) < MIN_SEPARATION_HOURS * 3600
               for ra in real_anchors):
            continue
        # TGE-window exclusion: skip if within 7d of first_bar
        if (t - first_bar).days < 7:
            continue
        picks.append(t)
    return picks


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="sample and print counts without running the labeler")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    sb = create_client(url, key)

    LOG.warning("PLACEBO backfill is a Second-Law-sensitive gate-day tool. "
                "Verify PLACEBO_A2b.md is finalized before running without --dry-run.")

    real_anchors_by_coin = _load_real_anchors(sb)
    rng = random.Random(PLACEBO_SEED)
    LOG.info("real-anchor coins: %d", len(real_anchors_by_coin))

    stats = {"sampled_total": 0, "coins_with_zero_placebos": 0,
             "labeled_rows": 0, "unlabelable_rows": 0}

    with httpx.Client(headers={"User-Agent": "defi-investor-research/0.3.0",
                               "Accept": "application/json"}) as client:
        for coin_name, real_anchors in sorted(real_anchors_by_coin.items()):
            placebos = _sample_placebos(coin_name, real_anchors, client, rng)
            stats["sampled_total"] += len(placebos)
            if not placebos:
                stats["coins_with_zero_placebos"] += 1
                LOG.info("coin=%s: 0 placebos (excluded window or no candles)", coin_name)
                continue
            LOG.info("coin=%s: %d placebos sampled", coin_name, len(placebos))
            if args.dry_run:
                continue

            for t in placebos:
                synth_event = EarnEvent(
                    product_id=f"PLACEBO_{coin_name}_{int(t.timestamp())}",
                    coin_name=coin_name,
                    second_biz_line="Placebo",
                    venue="placebo",
                    sold_out=True,
                    sold_out_first_seen_at=t.isoformat(),
                )
                per_horizon = label_event(synth_event, candles_client=client)
                if not per_horizon:
                    stats["unlabelable_rows"] += len(HORIZONS_HOURS)
                    continue
                for h, row in per_horizon.items():
                    payload = {
                        "venue": "placebo",
                        "product_id": synth_event.product_id,
                        "anchor_ts": t.isoformat(),
                        "labeler_version": _placebo_version(h),
                        "label": row.label,
                        "barrier_hit": row.barrier_hit,
                        "barrier_hit_ts": row.barrier_hit_ts,
                        "anchor_close_price": row.anchor_close_price,
                        "market": row.market,
                        "horizon_days": h // 24,
                        "k_up": row.k_upper, "k_down": row.k_lower,
                        "unlabelable_reason": row.unlabelable_reason,
                        "features": {"is_placebo": True},
                        "candles_provenance": row.candles_provenance,
                        "computed_at": row.computed_at,
                    }
                    sb.table("earn_event_labels").upsert(
                        payload, on_conflict="product_id,anchor_ts,labeler_version"
                    ).execute()
                    if row.label is None:
                        stats["unlabelable_rows"] += 1
                    else:
                        stats["labeled_rows"] += 1

    LOG.info("placebo backfill %s: %s",
             "DRY-RUN" if args.dry_run else "COMPLETE", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
