"""Health check — cadence + parser quality.

Runs on a schedule (see .github/workflows/health.yml). Two checks:

1. Cadence gap: max(last_seen_at) in earn_events. If > STALE_THRESHOLD_MIN
   minutes ago, alert.
2. Parser drift: any row with data_quality != 'complete'. Sample the coin
   names and alert.

On any failed check the script sends a Telegram card AND exits non-zero so
GitHub Actions marks the run failed (which triggers the account's default
email alert as a backup channel).

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
    TELEGRAM_BOT_TOKEN         optional; NoOp if absent
    TELEGRAM_CHAT_ID           optional; NoOp if absent
    STALE_THRESHOLD_MIN        default 30
    ACTIONS_URL                default None; if set, embedded as a link
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from defi_investor.notifier import build_notifier


LOG = logging.getLogger("defi_investor.health")


def _parse_iso(s: str) -> datetime:
    return datetime.fromisoformat(s.replace("Z", "+00:00"))


def main() -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_dotenv()

    threshold_min = int(os.environ.get("STALE_THRESHOLD_MIN", "30"))
    actions_url = os.environ.get("ACTIONS_URL")

    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2

    client = create_client(url, key)
    notifier = build_notifier()
    problems: list[str] = []

    # --- Check 1: cadence gap -------------------------------------------
    r = (
        client.table("earn_events")
        .select("last_seen_at")
        .order("last_seen_at", desc=True)
        .limit(1)
        .execute()
    )
    if not r.data:
        problems.append("earn_events is empty")
    else:
        last = _parse_iso(r.data[0]["last_seen_at"])
        now = datetime.now(timezone.utc)
        delta_min = int((now - last).total_seconds() // 60)
        LOG.info("last scrape %d min ago (%s)", delta_min, last.isoformat())
        if delta_min > threshold_min:
            notifier.notify_stall(
                last_scrape_at=last.isoformat(),
                minutes_ago=delta_min,
                threshold_min=threshold_min,
                actions_url=actions_url,
            )
            problems.append(f"cadence stall: {delta_min}m > {threshold_min}m")

    # --- Check 2: parser drift ------------------------------------------
    r = (
        client.table("earn_events")
        .select("coin_name,data_quality")
        .neq("data_quality", "complete")
        .execute()
    )
    if r.data:
        coin_names = sorted({row["coin_name"] for row in r.data})
        now_iso = datetime.now(timezone.utc).isoformat()
        notifier.notify_parser_drift(
            coin_names=coin_names,
            drift_count=len(r.data),
            observed_at=now_iso,
        )
        problems.append(f"parser drift on {len(r.data)} row(s)")
        LOG.warning("parser drift: %d rows, coins=%s",
                    len(r.data), coin_names[:10])
    else:
        LOG.info("parser drift: none")

    if problems:
        LOG.error("HEALTH FAIL: %s", "; ".join(problems))
        return 1
    LOG.info("HEALTH OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
