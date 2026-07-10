"""Backfill triple-barrier labels for resolved sold-out events.

Idempotent: skips (product_id, anchor_ts, labeler_version) rows that already
exist in earn_event_labels. Called nightly from .github/workflows/label.yml.

Discipline:
- Never overwrites. If the labeler_version changes, the runner re-labels
  the whole corpus into new PK rows (composite PK includes version).
- Unlabelable events are recorded with unlabelable_reason so we can see
  the corpus's health at a glance without hiding failures.
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

import httpx
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.features import event_features
from defi_investor.labeler import LABELER_VERSION, label_event
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

    stats = {"labeled": 0, "unlabelable": 0, "skipped_existing": 0,
             "labels": {1: 0, -1: 0, 0: 0}}

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
            label_row = label_event(event, candles_client=candles_client)
            if label_row is None:
                # Guard rail hit: event not eligible at all (e.g. not sold_out)
                continue

            features = event_features(event)  # cohort ctx computed later
            payload = asdict(label_row)
            payload["features"] = features
            # anchor_ts stringified already; anchor_ts must not be empty
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
