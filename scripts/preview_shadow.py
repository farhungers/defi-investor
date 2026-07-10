"""Shadow preview — what a Phase 4 alert WOULD look like if the PSR gate
were open.

Read-only. Prints to stdout. Zero Telegram traffic. Zero Supabase writes.

Purpose: let the operator eyeball the state of the labeled corpus during
the pilot without pretending to trade. Phase 4 alerter can only turn on
after METHOD §2.4's five gates pass — that's the rule saved in memory
(feedback_no_premature_signals.md), and this script exists so we don't
need to break it just to feel progress.
"""
from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv
from supabase import create_client

from defi_investor.backtest.stats import bet_stats, hhi


LOG = logging.getLogger("defi_investor.preview_shadow")


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

    r = (
        sb.table("earn_event_labels")
        .select("product_id,anchor_ts,label,realized_r,barrier_hit,market")
        .not_.is_("label", "null")
        .execute()
    )
    rows = r.data or []

    print("=" * 60)
    print("defi-investor SHADOW PREVIEW")
    print(f"resolved labels: {len(rows)}")
    if len(rows) < 5:
        print("Not enough resolved labels for a meaningful preview yet.")
        print("=" * 60)
        return 0

    by_label = {1: 0, -1: 0, 0: 0}
    r_values: list[float] = []
    for row in rows:
        l = row.get("label")
        if l in by_label:
            by_label[l] += 1
        if row.get("realized_r") is not None:
            r_values.append(float(row["realized_r"]))

    print(f"label distribution: dump=+1 → {by_label[1]}, "
          f"pump=-1 → {by_label[-1]}, timeout=0 → {by_label[0]}")

    stats = bet_stats(r_values)
    if stats is None:
        print("bet_stats: undefined (n<2 or zero stdev)")
        print("=" * 60)
        return 0

    h_plus = hhi(r_values, side="positive")
    h_minus = hhi(r_values, side="negative")

    print(f"n = {stats.n}")
    print(f"mean R      = {stats.mean_r:+.4f}")
    print(f"stdev R     = {stats.stdev_r:.4f}")
    print(f"Sharpe      = {stats.sharpe:+.4f}")
    print(f"skew        = {stats.skew:+.3f}")
    print(f"kurt        = {stats.kurt:.3f}")
    print(f"PSR vs 0    = {stats.psr_vs_zero:.3f}   (gate: >= 0.95)")
    if h_plus is not None:
        print(f"HHI winners = {h_plus:.3f}   (gate: <= 0.15)")
    if h_minus is not None:
        print(f"HHI losers  = {h_minus:.3f}")

    gate_pass = (
        stats.n >= 30
        and stats.mean_r > 0
        and stats.psr_vs_zero >= 0.95
        and (h_plus is None or h_plus <= 0.15)
    )
    print()
    print(f"GATE PROVISIONAL: {'PASS' if gate_pass else 'NOT YET'}")
    print("Note: this is a preview. Full Phase 3 gate needs confound splits")
    print("      (age / regime / control-arm) — see METHOD.md §2.4.")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
