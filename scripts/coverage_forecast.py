"""Coverage forecast for the A2b gate (n>=30 primary by 2026-09-30).

Corpus arithmetic on already-existing sold-out events. Answers one
question: given the historical rate of labelable sold-outs, are we on
track to hit n>=30 by the pre-committed gate date?

Explicitly NOT signal work. This does not read labels, does not compute
returns, does not slice by outcome. It only counts labelable events over
time and extrapolates. Discipline-safe under the Second Law.

The gate is per-horizon on directional {+1, -1} labels. Directional n
is <= labelable-event n (some events resolve to 0 = time barrier).
This script forecasts labelable-event n and notes the ceiling.

Read-only. Zero writes.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import os
import sys
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

from dotenv import load_dotenv
from supabase import create_client


LOG = logging.getLogger("defi_investor.coverage_forecast")

GATE_DATE_ISO = "2026-09-30T23:59:59+00:00"
GATE_TARGET_N = 30


def _parse_ts(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _rate_per_week(events: list[dict], window_days: int, now: datetime) -> float:
    """Sold-outs per week within the last `window_days`, based on
    sold_out_first_seen_at."""
    cutoff = now - timedelta(days=window_days)
    n = sum(
        1 for e in events
        if (ts := _parse_ts(e.get("sold_out_first_seen_at"))) is not None
        and ts >= cutoff
    )
    return n / (window_days / 7.0)


def main() -> int:
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    load_dotenv()
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing")
        return 2
    sb = create_client(url, key)

    now = datetime.now(timezone.utc)
    gate_date = _parse_ts(GATE_DATE_ISO)
    assert gate_date is not None
    days_to_gate = (gate_date - now).total_seconds() / 86400.0

    r = (
        sb.table("earn_events")
        .select("venue,product_id,coin_name,sold_out,sold_out_first_seen_at,first_seen_at")
        .eq("sold_out", True)
        .execute()
    )
    sold_out = r.data or []
    dated = [e for e in sold_out if _parse_ts(e.get("sold_out_first_seen_at"))]
    undated = len(sold_out) - len(dated)

    by_venue: dict[str, list[dict]] = defaultdict(list)
    for e in dated:
        by_venue[e.get("venue") or "bitget"].append(e)

    lines = [
        "=" * 70,
        "defi-investor - A2b Coverage Forecast (corpus arithmetic only)",
        f"now:            {now.strftime('%Y-%m-%d %H:%M UTC')}",
        f"gate date:      {gate_date.strftime('%Y-%m-%d %H:%M UTC')}",
        f"days to gate:   {days_to_gate:.1f}  (~{days_to_gate/7:.1f} weeks)",
        f"gate target:    n >= {GATE_TARGET_N} directional (per horizon)",
        "-" * 70,
        "Current corpus (sold_out=True, all venues)",
        f"  total sold-out events:            {len(sold_out)}",
        f"  with sold_out_first_seen_at:      {len(dated)}  (undated: {undated})",
    ]

    for venue, evs in sorted(by_venue.items()):
        first_ts = min(_parse_ts(e["sold_out_first_seen_at"]) for e in evs)
        distinct_coins = len({e.get("coin_name") for e in evs if e.get("coin_name")})
        lines.append(
            f"  {venue:<8}  n={len(evs):3d}  "
            f"first sold-out: {first_ts.strftime('%Y-%m-%d')}  "
            f"distinct coins: {distinct_coins}"
        )

    lines.append("-" * 70)
    lines.append("Rate windows (sold-outs per week, from sold_out_first_seen_at)")
    windows = [7, 14, 30, 60, 90]
    for w in windows:
        overall = _rate_per_week(dated, w, now)
        per_venue = " · ".join(
            f"{v}:{_rate_per_week(evs, w, now):.2f}"
            for v, evs in sorted(by_venue.items())
        )
        lines.append(f"  last {w:3d}d: {overall:5.2f}/wk  ({per_venue})")

    lines.append("-" * 70)
    lines.append("Projection to gate (linear extrapolation from each window's rate)")
    n_now = len(dated)
    weeks_to_gate = days_to_gate / 7.0
    for w in windows:
        rate = _rate_per_week(dated, w, now)
        projected_new = rate * weeks_to_gate
        projected_total = n_now + projected_new
        # Ceiling caveat: directional-n <= event-n; the current empirical
        # ratio at 24h horizon was 4/18 directional (Session 5), which is
        # a n=6 read and not extrapolation material. Report the raw ceiling
        # only and let the operator decide.
        margin = projected_total - GATE_TARGET_N
        status = "on track" if margin >= 0 else f"short by {-margin:.1f}"
        lines.append(
            f"  window {w:3d}d rate: n_at_gate = {projected_total:5.1f}  "
            f"({status}; ceiling only, directional-n is <=)"
        )

    lines += [
        "-" * 70,
        "Caveats:",
        "  1. This forecasts LABELABLE EVENT count, not DIRECTIONAL LABEL count.",
        "     The A2b gate needs n>=30 directional {+1,-1} per horizon; some",
        "     events resolve to 0 (time barrier). Directional-n <= event-n.",
        "  2. Extrapolation is linear from a window's observed rate. Real",
        "     sold-out rate is not stationary (Binance came online 2026-07-28",
        "     and roughly doubles intake vs Bitget-only baseline).",
        "  3. This is NOT a decision to accept or reject the hypothesis. It",
        "     answers only: is the corpus growing fast enough to trigger the",
        "     gate on the pre-committed date?",
        "=" * 70,
    ]
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
