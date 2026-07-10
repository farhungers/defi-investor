"""Nightly data-quality dashboard.

Reads Supabase, prints a compact operator-oriented health snapshot:

- earn_events counts by second_biz_line and status
- Recent status transitions (last 24h and 7d)
- Distinct coins observed
- Labels rollup by unlabelable_reason vs resolved
- Confound coverage (how many labels have each tag populated)
- Recent scrape freshness

Read-only. Zero writes. Meant for eyeballing during pilot burn.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone

from dotenv import load_dotenv
from supabase import create_client


LOG = logging.getLogger("defi_investor.quality_dashboard")


def _iso_lookback(days: float) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


def main() -> int:
    logging.basicConfig(level=logging.INFO)
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    sb = create_client(url, key)

    print("=" * 70)
    print("defi-investor · Data Quality Dashboard")
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    print(f"generated: {now_iso}")

    # --- earn_events overview ---------------------------------------------
    r = sb.table("earn_events").select("second_biz_line,status,coin_name,sold_out,last_seen_at").execute()
    events = r.data or []
    print("-" * 70)
    print(f"earn_events rows: {len(events)}")
    fam = Counter(e.get("second_biz_line") for e in events)
    for f, n in fam.most_common():
        print(f"  {f:<12} {n}")

    status_ct = Counter(e.get("status") for e in events)
    print("  by status:")
    for s in sorted(status_ct):
        print(f"    status={s}: {status_ct[s]}")

    n_sold = sum(1 for e in events if e.get("sold_out"))
    print(f"  sold_out=True:   {n_sold}")

    coins = {e.get("coin_name") for e in events if e.get("coin_name")}
    print(f"  distinct coins:  {len(coins)}")

    # scrape freshness
    last_seen = [e.get("last_seen_at") for e in events if e.get("last_seen_at")]
    if last_seen:
        print(f"  max(last_seen_at): {max(last_seen)}")

    # --- status transitions ------------------------------------------------
    for window_d, label in ((1, "24h"), (7, "7d")):
        r = (
            sb.table("earn_events_status_log")
            .select("old_status,new_status", count="exact")
            .gte("observed_at", _iso_lookback(window_d))
            .execute()
        )
        rows = r.data or []
        trans = Counter((row.get("old_status"), row.get("new_status")) for row in rows)
        print(f"  transitions last {label:>3}: {sum(trans.values())} "
              f"({', '.join(f'{a}->{b}:{n}' for (a,b),n in trans.most_common(5))})")

    # --- labels ------------------------------------------------------------
    r = sb.table("earn_event_labels").select("*").execute()
    labels = r.data or []
    print("-" * 70)
    print(f"earn_event_labels rows: {len(labels)}")
    ver_ct = Counter(l.get("labeler_version") for l in labels)
    for v, n in ver_ct.most_common():
        print(f"  labeler_version={v}: {n}")

    reasons = Counter(l.get("unlabelable_reason") for l in labels)
    print("  by unlabelable_reason:")
    for reason, n in reasons.most_common():
        print(f"    {reason!r}: {n}")

    resolved = [l for l in labels if l.get("label") is not None]
    print(f"  resolved (label != NULL): {len(resolved)}")
    if resolved:
        by_label = Counter(l.get("label") for l in resolved)
        print(f"    +1 dumped: {by_label[1]}")
        print(f"    -1 pumped: {by_label[-1]}")
        print(f"     0 T2:     {by_label[0]}")

    # --- confound coverage -------------------------------------------------
    confound_keys = [
        "bitget_listing_age_days", "within_7d_of_tge",
        "btc_ret_7d_prior", "perp_vol_change_prior_24h",
    ]
    print("  confound coverage:")
    for k in confound_keys:
        populated = sum(1 for l in labels if l.get(k) is not None)
        pct = (populated / len(labels) * 100) if labels else 0
        print(f"    {k:<32} {populated}/{len(labels)} ({pct:.0f}%)")

    print("=" * 70)
    return 0


if __name__ == "__main__":
    sys.exit(main())
