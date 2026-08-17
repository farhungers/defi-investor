"""Backfill v0.3.0 triple-barrier labels for resolved sold-out events.

Parallel to `scripts/backfill_labels.py` (which handles v0.2.1). Both may
run against the same corpus; each labeler's rows live under a distinct
`labeler_version` in the composite PK, so they never collide.

v0.3.0 spec is pre-registered in `docs/preregistrations/HYPOTHESIS_A2b.md`.

Runs today. Idempotent by (venue, product_id, anchor_ts, labeler_version)
plus the horizon (stored inside features JSONB to avoid a schema change;
the composite PK already includes labeler_version so overlap is safe).

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from dataclasses import asdict
from typing import Optional

import httpx
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.confounds import compute_confounds
from defi_investor.context import cohort_context
from defi_investor.features import event_features
from defi_investor.labelers.triple_barrier_v030 import (
    HORIZONS_HOURS, LABELER_VERSION, LabelRowV030, label_event,
)
from defi_investor.models import EarnEvent


LOG = logging.getLogger("defi_investor.backfill_labels_v030")


def _already_labeled(
    sb, venue: str, product_id: str, *, retry_unlabelable: bool = False,
) -> bool:
    """True iff a v0.3.0 row exists that should NOT be re-attempted.

    Default: any row is treated as "done" — v0.3.0 emits 3 rows per event
    (one per horizon) so presence of any means the event was processed.

    retry_unlabelable=True: rows with unlabelable_reason set do NOT count,
    so events previously blocked by fetcher/label bugs can be re-attempted
    after the underlying issue is fixed. Used to recover the 2026-07-29
    A2b backfill's 27/27 unlabelable events after fetch_candles paging fix.
    """
    q = (
        sb.table("earn_event_labels")
        .select("unlabelable_reason")
        .eq("venue", venue)
        .eq("product_id", product_id)
        .like("labeler_version", f"{LABELER_VERSION}%")
    )
    if retry_unlabelable:
        q = q.is_("unlabelable_reason", "null")
    r = q.limit(1).execute()
    return bool(r.data)


def _has_clean_anchor(
    sb, venue: str, product_id: str, *, sold_out_first_seen_at: Optional[str] = None,
) -> bool:
    """True iff we can point to a defensible sold-out anchor moment.

    Bitget: transition into status=6 recorded in earn_events_status_log
    (per-tick observation of the phase change).

    Binance: no per-tick status transitions are captured; the parser is a
    diff-detector that stamps sold_out_first_seen_at when a coin first
    appears in the sold-out list. That timestamp IS the anchor witness for
    Binance events. Presence of the field is sufficient.
    """
    if venue == "binance":
        return bool(sold_out_first_seen_at)
    r = (
        sb.table("earn_events_status_log")
        .select("id")
        .eq("venue", venue)
        .eq("product_id", product_id)
        .eq("new_status", 6)
        .limit(1)
        .execute()
    )
    return bool(r.data)


def _row_to_payload(row: LabelRowV030, features: dict, confounds: dict) -> dict:
    """Map LabelRowV030 -> earn_event_labels row.

    The existing table (migration 003 + 004 + 009) has columns designed
    around v0.2.1. v0.3.0-specific fields (sigma_20d, upper_barrier,
    lower_barrier, horizon_hours, barrier_hit_price) live inside features
    JSONB so no schema change is required.
    """
    v030_extras = {
        "labeler_v030_horizon_hours": row.horizon_hours,
        "labeler_v030_sigma_20d": row.sigma_20d,
        "labeler_v030_upper_barrier": row.upper_barrier,
        "labeler_v030_lower_barrier": row.lower_barrier,
        "labeler_v030_barrier_hit_price": row.barrier_hit_price,
        "labeler_v030_k_upper": row.k_upper,
        "labeler_v030_k_lower": row.k_lower,
    }
    merged_features = {**features, **v030_extras}

    return {
        "venue": row.venue,
        "product_id": row.product_id,
        "anchor_ts": row.anchor_ts,
        "labeler_version": row.labeler_version,
        "label": row.label,
        "realized_r": None,  # v0.3.0 is categorical; no realized_r
        "barrier_hit": row.barrier_hit,
        "barrier_hit_ts": row.barrier_hit_ts,
        "anchor_close_price": row.anchor_close_price,
        "atr_4h_at_anchor": None,  # unused by v0.3.0
        "market": row.market,
        "horizon_days": row.horizon_hours // 24 if row.horizon_hours else None,
        "k_up": row.k_upper,
        "k_down": row.k_lower,
        "unlabelable_reason": row.unlabelable_reason,
        "features": merged_features,
        "candles_provenance": row.candles_provenance,
        "computed_at": row.computed_at,
        # Confounds
        "bitget_listing_age_days": confounds.get("bitget_listing_age_days"),
        "within_7d_of_tge": confounds.get("within_7d_of_tge"),
        "btc_ret_7d_prior": confounds.get("btc_ret_7d_prior"),
        "perp_vol_change_prior_24h": confounds.get("perp_vol_change_prior_24h"),
        "perp_oi_pct_change_prior_24h": confounds.get("perp_oi_pct_change_prior_24h"),
        "known_vest_unlock_within_3d": confounds.get("known_vest_unlock_within_3d"),
        "btc_30d_realized_vol": confounds.get("btc_30d_realized_vol"),
        "btc_ret_30d_prior": confounds.get("btc_ret_30d_prior"),
    }


def _upsert(sb, payload: dict) -> None:
    # Composite PK is (product_id, anchor_ts, labeler_version). Since one
    # event produces 3 rows in v0.3.0 (one per horizon), we distinguish
    # them by encoding the horizon into anchor_ts... actually the composite
    # PK doesn't include horizon, so multiple horizons for the same event
    # would collide. Solution: encode horizon in labeler_version:
    # '0.3.0#h24', '0.3.0#h48', '0.3.0#h168'. This preserves the PK
    # constraint without needing a schema change.
    (
        sb.table("earn_event_labels")
        .upsert(payload, on_conflict="product_id,anchor_ts,labeler_version")
        .execute()
    )


def _versioned(base_version: str, horizon_hours: int) -> str:
    """Encode horizon into labeler_version so 3 horizons don't collide on PK."""
    return f"{base_version}#h{horizon_hours}"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--retry-unlabelable", action="store_true",
        help="Re-attempt events whose existing v0.3.0 rows all have "
             "unlabelable_reason set. Use after fixing a fetcher or labeler "
             "bug that produced spurious unlabelable rows.",
    )
    args = parser.parse_args()

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

    # Both venues. Bitget events have status=6 sold-outs from the transition
    # log; Binance events flip sold_out=True via the diff-detector.
    # Filter on `sold_out_first_seen_at IS NOT NULL` (ever-sold-out), not
    # on `sold_out=True` (currently-sold-out). Bitget products can re-open
    # after selling out; the anchor moment is historical and its label is
    # still meaningful.
    r = (
        sb.table("earn_events")
        .select("*")
        .not_.is_("sold_out_first_seen_at", "null")
        .execute()
    )
    events_raw = r.data or []
    LOG.info("sold-out candidates (all venues): %d", len(events_raw))

    stats = {
        "labeled_events": 0, "labeled_rows": 0,
        "unlabelable_rows": 0, "stale_anchor": 0,
        "skipped_existing": 0,
        "labels": {1: 0, -1: 0, 0: 0},
        "by_horizon": {h: {"labeled": 0, "unlabelable": 0} for h in HORIZONS_HOURS},
    }

    with httpx.Client(
        headers={"User-Agent": "defi-investor-research/0.3.0",
                 "Accept": "application/json"},
    ) as candles_client:
        for row in events_raw:
            venue = row.get("venue", "bitget")
            product_id = row["product_id"]

            if _already_labeled(sb, venue, product_id,
                                retry_unlabelable=args.retry_unlabelable):
                stats["skipped_existing"] += 1
                continue

            event = EarnEvent.from_dict(row)

            if not _has_clean_anchor(
                sb, venue, product_id,
                sold_out_first_seen_at=row.get("sold_out_first_seen_at"),
            ):
                stats["stale_anchor"] += 1
                LOG.debug("stale anchor: %s/%s", venue, product_id)
                continue

            per_horizon = label_event(event, candles_client=candles_client)
            if not per_horizon:
                continue

            # Shared context computed once per event
            cohort_ctx = None
            try:
                cohort_ctx = cohort_context(event, sb)
            except Exception as e:  # noqa: BLE001
                LOG.warning("cohort_context failed for %s: %s", product_id, e)

            features = event_features(event, cohort_ctx=cohort_ctx)

            anchor_ts_for_confounds = (
                event.sold_out_first_seen_at or event.last_seen_at or ""
            )
            confounds = {}
            try:
                confounds = compute_confounds(
                    event.coin_name, anchor_ts_for_confounds,
                    client=candles_client, sb_client=sb,
                )
            except Exception as e:  # noqa: BLE001
                LOG.warning("confounds failed for %s: %s", product_id, e)

            any_labeled = False
            for horizon_hours, label_row in per_horizon.items():
                payload = _row_to_payload(label_row, features, confounds)
                # Rewrite labeler_version so 3 horizons don't collide on PK
                payload["labeler_version"] = _versioned(label_row.labeler_version, horizon_hours)

                if not payload["anchor_ts"]:
                    continue

                try:
                    _upsert(sb, payload)
                except Exception as e:  # noqa: BLE001
                    LOG.error("upsert failed for %s h=%d: %s", product_id, horizon_hours, e)
                    continue

                if label_row.label is None:
                    stats["unlabelable_rows"] += 1
                    stats["by_horizon"][horizon_hours]["unlabelable"] += 1
                else:
                    stats["labeled_rows"] += 1
                    stats["by_horizon"][horizon_hours]["labeled"] += 1
                    stats["labels"][label_row.label] += 1
                    any_labeled = True

            if any_labeled:
                stats["labeled_events"] += 1

    LOG.info("v0.3.0 backfill complete: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
