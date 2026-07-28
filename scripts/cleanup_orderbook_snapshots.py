"""Delete orderbook_snapshots_l2 rows older than N hours.

Free-tier Supabase substitute for pg_cron. Run periodically (e.g. every
hour from cron or a scheduled task) to keep storage under the 500 MB
free-tier cap.

The A3 feature extractor only needs the 10-minute pre-event window per
sold-out event. Once the A3 backfill has run for a sold-out event's
pre-window, the raw snapshots for that window are no longer needed.
Conservative default is 24h retention — enough time for a sold-out
event to happen and its A3 backfill to consume the window.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client


LOG = logging.getLogger("defi_investor.cleanup_orderbook_snapshots")

DEFAULT_RETAIN_HOURS = 24


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()

    parser = argparse.ArgumentParser()
    parser.add_argument("--retain-hours", type=int, default=DEFAULT_RETAIN_HOURS,
                        help=f"delete rows older than this many hours (default: {DEFAULT_RETAIN_HOURS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would be deleted, don't delete")
    args = parser.parse_args()

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    sb = create_client(url, key)

    cutoff = datetime.now(timezone.utc) - timedelta(hours=args.retain_hours)
    cutoff_iso = cutoff.isoformat()

    r = (
        sb.table("orderbook_snapshots_l2")
        .select("*", count="exact", head=True)
        .lt("received_at", cutoff_iso)
        .execute()
    )
    n_stale = r.count or 0

    if n_stale == 0:
        LOG.info("no stale rows (cutoff=%s); nothing to do", cutoff_iso)
        return 0

    if args.dry_run:
        LOG.info("DRY RUN: would delete %d rows with received_at < %s",
                 n_stale, cutoff_iso)
        return 0

    (
        sb.table("orderbook_snapshots_l2")
        .delete()
        .lt("received_at", cutoff_iso)
        .execute()
    )
    LOG.info("deleted %d rows with received_at < %s (retain=%dh)",
             n_stale, cutoff_iso, args.retain_hours)
    return 0


if __name__ == "__main__":
    sys.exit(main())
