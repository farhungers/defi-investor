"""Supabase keepalive: write one row, prune rows older than 30 days.

Runs on a 3-day cron via .github/workflows/keepalive.yml. Keeps the
free-tier project from auto-pausing after 7 days of inactivity.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client


LOG = logging.getLogger("defi_investor.heartbeat")

RETAIN_DAYS = 30
SOURCE = "keepalive-gh-actions"


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

    sb.table("healthchecks").insert({"source": SOURCE}).execute()
    LOG.info("heartbeat inserted (source=%s)", SOURCE)

    cutoff = (datetime.now(timezone.utc) - timedelta(days=RETAIN_DAYS)).isoformat()
    sb.table("healthchecks").delete().lt("ts", cutoff).execute()
    LOG.info("pruned rows with ts < %s", cutoff)
    return 0


if __name__ == "__main__":
    sys.exit(main())
