"""Cohort context for observation cards.

Called once per alert, does at most one Supabase query, returns a dict the
card formatter uses to fill the COHORT / PEERS / WHY sections. If the client
is None or the query fails, returns None and the card renders without those
sections — no hard dependency.
"""
from __future__ import annotations

import logging
import statistics
from datetime import datetime, timezone
from typing import Optional

from .models import EarnEvent


LOG = logging.getLogger("defi_investor.context")

# APR-band tolerance for grouping "same APR" — Bitget adjusts by small deltas.
_APR_BAND_RELATIVE = 0.02  # ±2%


def _parse_iso(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _days_between(a: Optional[str], b: Optional[str]) -> Optional[float]:
    da = _parse_iso(a)
    db = _parse_iso(b)
    if da is None or db is None:
        return None
    return (db - da).total_seconds() / 86400.0


def _fmt_days(d: Optional[float]) -> str:
    if d is None:
        return "—"
    if d < 1:
        h = d * 24
        return f"{h:.1f}h"
    if d < 30:
        return f"{d:.1f}d"
    return f"{d:.0f}d"


def cohort_context(event: EarnEvent, sb_client) -> Optional[dict]:
    """Query Supabase for the APR-cohort this event belongs to.

    Returns:
        {
            "cohort_size":   int,   # rows in same APR band + family
            "n_active":      int,   # status != 6
            "n_sold":        int,   # status == 6
            "median_life_d": float | None,  # median (sold_out_first_seen - start_time)
            "this_life_d":   float | None,  # THIS event's lifespan
            "band_lo":       float,  # APR band lower
            "band_hi":       float,  # APR band upper
            "distinct_coins": int,
        }
        or None if the client can't be reached or event has no max_apy.
    """
    if sb_client is None or event.max_apy is None or event.second_biz_line is None:
        return None
    apr = float(event.max_apy)
    band = apr * _APR_BAND_RELATIVE
    lo = apr - band
    hi = apr + band

    try:
        r = (
            sb_client
            .table("earn_events")
            .select("product_id,coin_name,max_apy,status,sold_out,"
                    "start_time,sold_out_first_seen_at,first_seen_at")
            .gte("max_apy", lo)
            .lte("max_apy", hi)
            .eq("second_biz_line", event.second_biz_line)
            .execute()
        )
        rows = r.data or []
    except Exception as e:  # noqa: BLE001
        LOG.warning("cohort query failed: %s", e)
        return None

    n_active = sum(1 for r in rows if r.get("status") != 6)
    n_sold = sum(1 for r in rows if r.get("status") == 6)
    distinct_coins = len({r.get("coin_name") for r in rows if r.get("coin_name")})

    # Median lifespan: for rows that DID sell out, days between start_time and sold_out_first_seen_at
    lifespans_d = []
    for r in rows:
        if r.get("status") == 6:
            d = _days_between(r.get("start_time"), r.get("sold_out_first_seen_at"))
            if d is not None and d >= 0:
                lifespans_d.append(d)
    median_life_d = statistics.median(lifespans_d) if lifespans_d else None

    # This event's own lifespan (if it just sold out) or age-since-open (if active)
    this_life_d = None
    if event.status == 6:
        this_life_d = _days_between(event.start_time, event.sold_out_first_seen_at)
    else:
        now_iso = datetime.now(timezone.utc).isoformat()
        this_life_d = _days_between(event.start_time, now_iso)

    return {
        "cohort_size": len(rows),
        "n_active": n_active,
        "n_sold": n_sold,
        "median_life_d": median_life_d,
        "this_life_d": this_life_d,
        "band_lo": lo,
        "band_hi": hi,
        "distinct_coins": distinct_coins,
    }


def rarity_stars(event: EarnEvent, *, event_type: str) -> int:
    """1-5 stars based on how unusual this observation is.

    Rules:
    - reopened: always 4 (rare status flip)
    - sold_out and new_listing: scale by max_apy
        max_apy >= 100  →  5
        max_apy >= 50   →  4
        max_apy >= 20   →  3
        max_apy >= 5    →  2
        else            →  1
    """
    if event_type == "reopened":
        return 4
    apr = event.max_apy or 0
    if apr >= 100:
        return 5
    if apr >= 50:
        return 4
    if apr >= 20:
        return 3
    if apr >= 5:
        return 2
    return 1


def stars_glyph(n: int) -> str:
    n = max(0, min(5, n))
    return "★" * n + "☆" * (5 - n)


def why_sold_out(event: EarnEvent, ctx: Optional[dict]) -> str:
    """One-paragraph rationale for the sold-out card."""
    parts = []
    apr = event.max_apy
    if apr is not None and apr >= 100:
        parts.append("Triple-digit APR pools are the H3 hypothesis cohort — high pump-and-dump prior.")
    elif apr is not None and apr >= 50:
        parts.append("High-APR new-listing pool matching the H3 cohort profile.")
    if ctx and ctx.get("median_life_d") is not None and ctx.get("this_life_d") is not None:
        med = ctx["median_life_d"]
        life = ctx["this_life_d"]
        if med > 0:
            ratio = life / med
            if ratio >= 1.5:
                parts.append(f"Lived {life:.0f}d, {ratio:.1f}× the cohort median ({med:.0f}d) — slower burn than peers.")
            elif ratio <= 0.5:
                parts.append(f"Lived {life:.0f}d, {ratio:.1f}× the cohort median ({med:.0f}d) — burned fast.")
            else:
                parts.append(f"Lived {life:.0f}d, near cohort median ({med:.0f}d).")
    if ctx and ctx.get("n_active") == 0 and ctx.get("cohort_size", 0) > 1:
        parts.append("Entire APR band is now exhausted.")
    if not parts:
        parts.append("Status transition observed. No hypothesis-level context yet — n too small.")
    return " ".join(parts)


def why_new_listing(event: EarnEvent, ctx: Optional[dict]) -> str:
    parts = []
    apr = event.max_apy
    if apr is not None and apr >= 100:
        parts.append("Triple-digit APR bait-tier product — matches the H3 cohort profile.")
    elif apr is not None and apr >= 50:
        parts.append("High-APR pool that fits the H3 cohort we are labeling.")
    if ctx and ctx.get("cohort_size", 0) > 0:
        parts.append(
            f"{ctx['cohort_size']} peer(s) in the same APR band "
            f"({ctx['band_lo']:.1f}% – {ctx['band_hi']:.1f}%): "
            f"{ctx['n_active']} active, {ctx['n_sold']} sold-out across "
            f"{ctx['distinct_coins']} distinct coins."
        )
    if len(event.tiers) >= 2:
        apys = [t.get("apy") for t in event.tiers]
        parts.append(f"Multi-tier ladder ({len(event.tiers)} levels: {' → '.join(apys)}%) — stable-product shape, not bait.")
    if not parts:
        parts.append("New product observed. Add to corpus for Phase 2 labeling.")
    return " ".join(parts)


def why_reopened(event: EarnEvent, ctx: Optional[dict]) -> str:
    parts = ["Status flipped 6 → 2 (re-opened). This is rare — worth eyeballing."]
    if ctx and ctx.get("cohort_size", 0) > 1:
        parts.append(f"Same-APR cohort now has {ctx['n_active']} active / {ctx['n_sold']} sold.")
    if event.max_apy is not None and event.max_apy >= 50:
        parts.append("APR still in H3-cohort range — treat as a fresh observation on the timeline.")
    return " ".join(parts)
