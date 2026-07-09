"""One-shot smoke: send one card of each type to the configured chat.

Uses live Supabase to grab a real event (LAB) so cards render with true data.
Run once after wiring, then delete or gate behind an env var.

    python scripts/smoke_cards.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

from dotenv import load_dotenv
from supabase import create_client

from defi_investor.models import EarnEvent
from defi_investor.notifier import TelegramNotifier


def main() -> int:
    load_dotenv()
    url = os.environ["SUPABASE_URL"]
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    bot = os.environ["TELEGRAM_BOT_TOKEN"]
    chat = os.environ["TELEGRAM_CHAT_ID"]

    sb = create_client(url, key)

    # Real event — LAB has clean fields and a 58-day life so cards look full.
    r = sb.table("earn_events").select("*").eq("coin_name", "LAB").execute()
    lab = EarnEvent.from_dict(r.data[0])

    # Real multi-tier — USDT for the new-listing card so tier summary shines.
    r = sb.table("earn_events").select("*").eq("coin_name", "USDT").execute()
    usdt = EarnEvent.from_dict(r.data[0])

    notifier = TelegramNotifier(bot_token=bot, chat_id=chat)
    now_iso = datetime.now(timezone.utc).isoformat()
    actions_url = "https://github.com/farhungers/defi-investor/actions"

    print("Sending smoke cards...")

    print("  1/5 sold-out (LAB)")
    notifier.notify_sold_out(lab, observed_at=now_iso)

    print("  2/5 new-listing (USDT multi-tier)")
    notifier.notify_new_listing(usdt, observed_at=now_iso)

    print("  3/5 re-opened (LAB, pretend transition)")
    notifier.notify_reopened(lab, observed_at=now_iso)

    print("  4/5 stall (42 min ago)")
    notifier.notify_stall(
        last_scrape_at="2026-07-10T01:53:00+00:00",
        minutes_ago=42,
        threshold_min=30,
        actions_url=actions_url,
    )

    print("  5/5 parser drift (3 coins)")
    notifier.notify_parser_drift(
        coin_names=["ABC", "DEF", "GHI"],
        drift_count=3,
        observed_at=now_iso,
    )

    print("Done. Check the chat.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
