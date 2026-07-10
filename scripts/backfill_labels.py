"""Backfill triple-barrier labels for resolved sold-out events.

Idempotent: skips (product_id, anchor_ts, labeler_version) rows that already
exist in earn_event_labels. Called nightly from .github/workflows/label.yml.

Discipline:
- Never overwrites. If the labeler_version changes, the runner re-labels
  the whole corpus into new PK rows (composite PK includes version).
- Unlabelable events are recorded with unlabelable_reason so we can see
  the corpus's health at a glance without hiding failures.
- Stale-anchor filter: only events where we OBSERVED the 2→6 transition
  get labeled. Events that were already sold_out at first scrape have
  anchor_precision >> scrape cadence — labeling them measures residual,
  not fresh signal. Excluded from primary per METHOD §5.1.
- No Telegram output. Phase 2 is a background labeling job.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import os
import sys
from dataclasses import asdict
from datetime import datetime, timezone

import httpx
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.features import event_features
from defi_investor.labeler import (
    DEFAULT_HORIZON_DAYS, DEFAULT_K_DOWN, DEFAULT_K_UP, LABELER_VERSION,
    LabelRow, label_event,
)
from defi_investor.models import EarnEvent


LOG = logging.getLogger("defi_investor.backfill_labels")


def _already_labeled(sb, product_id: str, labeler_version: str) -> bool:
    r = (
        sb.table("earn_event_labels")
        .select("product_id")
        .eq("product_id", product_id)
        .eq("labeler_version", labeler_version)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def _has_clean_anchor(sb, product_id: str) -> bool:
    """True iff we recorded a status transition into sold-out (new_status=6).

    Events that were sold_out at first scrape have no such row, so
    sold_out_first_seen_at reflects only "when we first saw it," not
    when the pool actually saturated. Those go to stale_anchor.
    """
    r = (
        sb.table("earn_events_status_log")
        .select("id")
        .eq("product_id", product_id)
        .eq("new_status", 6)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def _stale_anchor_row(event: EarnEvent) -> LabelRow:
    """Compose a placeholder LabelRow flagging the event as excluded."""
    return LabelRow(
        product_id=event.product_id,
        anchor_ts=event.sold_out_first_seen_at or event.last_seen_at or "",
        labeler_version=LABELER_VERSION,
        label=None, realized_r=None,
        barrier_hit=None, barrier_hit_ts=None,
        anchor_close_price=None, atr_4h_at_anchor=None,
        market="none",
        horizon_days=DEFAULT_HORIZON_DAYS,
        k_up=DEFAULT_K_UP, k_down=DEFAULT_K_DOWN,
        unlabelable_reason="stale_anchor",
        candles_provenance={},
        computed_at=datetime.now(timezone.utc).isoformat(),
    )


def _upsert(sb, row_dict: dict) -> None:
    (
        sb.table("earn_event_labels")
        .upsert(row_dict, on_conflict="product_id,anchor_ts,labeler_version")
        .execute()
    )


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

    # Pull every sold-out event; the DB is small (< 500 rows in Phase 1).
    r = (
        sb.table("earn_events")
        .select("*")
        .eq("sold_out", True)
        .execute()
    )
    events_raw = r.data or []
    LOG.info("sold-out candidates: %d", len(events_raw))

    stats = {"labeled": 0, "unlabelable": 0, "stale_anchor": 0,
             "skipped_existing": 0, "labels": {1: 0, -1: 0, 0: 0}}

    # Reuse one httpx client across all candle fetches
    with httpx.Client(
        headers={"User-Agent": "defi-investor-research/0.2.0",
                 "Accept": "application/json"},
    ) as candles_client:
        for row in events_raw:
            product_id = row["product_id"]
            if _already_labeled(sb, product_id, LABELER_VERSION):
                stats["skipped_existing"] += 1
                continue

            event = EarnEvent.from_dict(row)

            # Stale-anchor filter (METHOD §5.1): only events where we
            # observed the 2→6 transition have anchor precision at
            # ±cadence. Everything else gets flagged and excluded.
            if not _has_clean_anchor(sb, product_id):
                label_row = _stale_anchor_row(event)
                payload = asdict(label_row)
                payload["features"] = event_features(event)
                if payload["anchor_ts"]:
                    try:
                        _upsert(sb, payload)
                        stats["stale_anchor"] += 1
                    except Exception as e:  # noqa: BLE001
                        LOG.error("stale-anchor upsert failed for %s: %s", product_id, e)
                continue

            label_row = label_event(event, candles_client=candles_client)
            if label_row is None:
                # Guard rail: event not eligible at all (e.g. not sold_out)
                continue

            features = event_features(event)  # cohort ctx computed later
            payload = asdict(label_row)
            payload["features"] = features
            if not payload["anchor_ts"]:
                LOG.warning("skipping %s — empty anchor_ts", product_id)
                continue

            try:
                _upsert(sb, payload)
            except Exception as e:  # noqa: BLE001
                LOG.error("upsert failed for %s: %s", product_id, e)
                continue

            if label_row.label is None:
                stats["unlabelable"] += 1
            else:
                stats["labeled"] += 1
                stats["labels"][label_row.label] += 1

    LOG.info("backfill complete: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
