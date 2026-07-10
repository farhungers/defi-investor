"""HTML card formatters for Telegram alerts.

Telegram HTML mode accepts: <b> <i> <u> <s> <code> <pre> <blockquote>
<a href> and \\n. Everything else must be HTML-escaped.

Design (visual density inspired by user's example cards; observation-honest):
- Header row: emoji · event type in CAPS · coin · family · star rarity
- One-line subtitle: what happened, in plain language
- Multiple sections, each with an emoji heading and an aligned <pre> block
- WHY THIS IS INTERESTING: quoted rationale grounded in cohort context
- Footer: observation timestamp · product_id · Bitget link

Observation cards only. No entry/stop/TP. See memory
feedback_no_premature_signals.md.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

from .context import (
    rarity_stars,
    stars_glyph,
    why_new_listing,
    why_reopened,
    why_sold_out,
)
from .models import EarnEvent


# ---------- helpers --------------------------------------------------------

def _e(s: object) -> str:
    return html.escape("" if s is None else str(s), quote=False)


def _fmt_apy(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 100:
        return f"{v:,.0f}%"
    return f"{v:,.2f}%"


def _fmt_amount(v: Optional[float], coin: str) -> str:
    if v is None:
        return f"— {coin}"
    if v >= 1_000_000:
        return f"{v/1_000_000:.2f}M {coin}"
    if v >= 1_000:
        return f"{v:,.0f} {coin}"
    if v >= 1:
        return f"{v:,.2f} {coin}"
    return f"{v:.4f} {coin}"


def _fmt_ts(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, TypeError):
        return _e(iso)


def _fmt_ts_relative(iso: Optional[str], now: Optional[datetime] = None) -> str:
    """'2026-05-12 07:54 UTC (58d ago)'."""
    if not iso:
        return "—"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        base = _fmt_ts(iso)
        n = now or datetime.now(timezone.utc)
        delta = n - dt
        days = int(delta.total_seconds() // 86400)
        if days >= 1:
            return f"{base} ({days}d ago)"
        hours = int(delta.total_seconds() // 3600)
        if hours >= 1:
            return f"{base} ({hours}h ago)"
        mins = int(delta.total_seconds() // 60)
        return f"{base} ({mins}m ago)"
    except (ValueError, TypeError):
        return _e(iso)


def _fmt_days(d: Optional[float]) -> str:
    if d is None:
        return "—"
    if d < 1:
        return f"{d*24:.1f}h"
    return f"{d:.1f}d"


def _tier_structure(ev: EarnEvent) -> str:
    tiers = ev.tiers or []
    if not tiers:
        return "no tiers"
    if len(tiers) == 1:
        return "single-tier"
    apys = [t.get("apy", "?") for t in tiers]
    return f"{len(tiers)}-tier · " + " → ".join(f"{a}%" for a in apys)


def _kv_block(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return ""
    label_w = max(len(k) for k, _ in rows)
    lines = [f"{k.ljust(label_w)}  {v}" for k, v in rows]
    return "<pre>" + _e("\n".join(lines)) + "</pre>"


def _family_link(second_biz_line: str) -> str:
    """Best-effort Bitget landing page for this family."""
    slug = {
        "Savings": "savings",
        "PosStaking": "pos-staking",
        "CashPlus": "cashplus",
        "FundMarket": "fundmarket",
        "SharkFin": "shark-fin",
        "Trend": "smart-trend",
    }.get(second_biz_line, "")
    if not slug:
        return "https://www.bitget.com/asia/earning"
    return f"https://www.bitget.com/asia/earning/{slug}"


def _footer(ev: EarnEvent, *, observed_at: str) -> str:
    link = _family_link(ev.second_biz_line)
    label = _e(ev.second_biz_line) or "Earn"
    return (
        f"<i>observed {_fmt_ts(observed_at)}</i>\n"
        f"<code>product {_e(ev.product_id)}</code>\n"
        f'<a href="{_e(link)}">Open {label} on Bitget →</a>'
    )


# ---------- section builders ----------------------------------------------

def _sec_structure(ev: EarnEvent) -> str:
    rows = [
        ("APR", _fmt_apy(ev.max_apy)),
        ("Structure", _tier_structure(ev)),
        ("Per-user cap", _fmt_amount(ev.per_user_cap_underlying, ev.coin_name)),
        ("Family", _e(ev.second_biz_line)),
    ]
    return "📊 <b>STRUCTURE</b>\n" + _kv_block(rows)


def _sec_timing_sold_out(ev: EarnEvent, *, observed_at: str) -> str:
    rows = [
        ("Opened", _fmt_ts_relative(ev.start_time)),
        ("First seen", _fmt_ts(ev.first_seen_at)),
        ("Sold-out seen", _fmt_ts(ev.sold_out_first_seen_at or observed_at)),
    ]
    try:
        dt_open = datetime.fromisoformat((ev.start_time or "").replace("Z", "+00:00"))
        dt_sold = datetime.fromisoformat(
            (ev.sold_out_first_seen_at or observed_at).replace("Z", "+00:00")
        )
        life_d = (dt_sold - dt_open).total_seconds() / 86400.0
        rows.append(("Time-to-sell", _fmt_days(life_d)))
    except (ValueError, TypeError, AttributeError):
        pass
    return "🕒 <b>TIMING</b>\n" + _kv_block(rows)


def _sec_timing_new_listing(ev: EarnEvent, *, observed_at: str) -> str:
    rows = [
        ("Product opened", _fmt_ts_relative(ev.start_time)),
        ("First scraped", _fmt_ts(observed_at)),
    ]
    if ev.period_days:
        rows.append(("Period", f"{ev.period_days} days"))
    if ev.lock_model is not None:
        rows.append(("Lock model", "yes" if ev.lock_model else "no"))
    return "🕒 <b>TIMING</b>\n" + _kv_block(rows)


def _sec_cohort(ctx: Optional[dict]) -> str:
    if not ctx:
        return ""
    rows = [
        ("Cohort size", f"{ctx['cohort_size']} rows · {ctx['distinct_coins']} coins"),
        ("Split", f"{ctx['n_active']} active · {ctx['n_sold']} sold-out"),
    ]
    if ctx.get("median_life_d") is not None:
        rows.append(("Median lifespan", _fmt_days(ctx["median_life_d"])))
    band = f"{ctx['band_lo']:.2f}% – {ctx['band_hi']:.2f}%"
    return f"👥 <b>COHORT</b>  <i>({band}, same family)</i>\n" + _kv_block(rows)


def _sec_tiers(ev: EarnEvent) -> str:
    if not ev.tiers or len(ev.tiers) < 2:
        return ""
    rows = []
    for t in ev.tiers:
        lvl = t.get("rateLevel", "?")
        apy = t.get("apy", "?")
        cap = t.get("maxStepValue", "?")
        rows.append((f"L{lvl}", f"{apy}% APR up to {cap} {ev.coin_name}"))
    return "🪜 <b>TIER LADDER</b>\n" + _kv_block(rows)


def _sec_why(text: str) -> str:
    return "💡 <b>WHY THIS IS INTERESTING</b>\n<blockquote>" + _e(text) + "</blockquote>"


# ---------- public card entry points --------------------------------------

def sold_out_card(ev: EarnEvent, *, observed_at: str, ctx: Optional[dict] = None) -> str:
    stars = stars_glyph(rarity_stars(ev, event_type="sold_out"))
    header = (
        f"🔴 <b>SOLD OUT</b>  ·  <b>{_e(ev.coin_name)}</b> "
        f"{_e(ev.second_biz_line)}  <i>{stars}</i>"
    )
    subtitle = (
        f"<i>{_fmt_apy(ev.max_apy)} APR pool exhausted</i>"
    )
    sections = [
        header,
        subtitle,
        _sec_structure(ev),
        _sec_timing_sold_out(ev, observed_at=observed_at),
        _sec_cohort(ctx),
        _sec_why(why_sold_out(ev, ctx)),
        _footer(ev, observed_at=observed_at),
    ]
    return "\n\n".join(s for s in sections if s)


def new_listing_card(ev: EarnEvent, *, observed_at: str, ctx: Optional[dict] = None) -> str:
    stars = stars_glyph(rarity_stars(ev, event_type="new_listing"))
    header = (
        f"🆕 <b>NEW LISTING</b>  ·  <b>{_e(ev.coin_name)}</b> "
        f"{_e(ev.second_biz_line)}  <i>{stars}</i>"
    )
    subtitle = f"<i>first seen in the catalog · {_fmt_apy(ev.max_apy)} APR</i>"
    sections = [
        header,
        subtitle,
        _sec_structure(ev),
        _sec_timing_new_listing(ev, observed_at=observed_at),
        _sec_tiers(ev),
        _sec_cohort(ctx),
        _sec_why(why_new_listing(ev, ctx)),
        _footer(ev, observed_at=observed_at),
    ]
    return "\n\n".join(s for s in sections if s)


def reopened_card(ev: EarnEvent, *, observed_at: str, ctx: Optional[dict] = None) -> str:
    stars = stars_glyph(rarity_stars(ev, event_type="reopened"))
    header = (
        f"🟢 <b>RE-OPENED</b>  ·  <b>{_e(ev.coin_name)}</b> "
        f"{_e(ev.second_biz_line)}  <i>{stars}</i>"
    )
    subtitle = "<i>status flipped 6 → 2 (unusual)</i>"
    sections = [
        header,
        subtitle,
        _sec_structure(ev),
        _sec_cohort(ctx),
        _sec_why(why_reopened(ev, ctx)),
        _footer(ev, observed_at=observed_at),
    ]
    return "\n\n".join(s for s in sections if s)


def stall_card(*, last_scrape_at: str, minutes_ago: int, threshold_min: int,
               actions_url: Optional[str] = None) -> str:
    header = "⚠️ <b>SCRAPER STALL</b>  ·  <i>operational alert</i>"
    subtitle = f"<i>last cadence tick more than {threshold_min}m ago</i>"
    rows = [
        ("Last scrape", f"{_fmt_ts(last_scrape_at)} ({minutes_ago}m ago)"),
        ("Threshold", f"{threshold_min} min"),
        ("Expected", "every 15 min"),
        ("Missed runs", f"~{max(0, minutes_ago // 15 - 1)}"),
    ]
    body = "📶 <b>STATUS</b>\n" + _kv_block(rows)
    causes = (
        "🧭 <b>WHAT TO CHECK</b>\n<blockquote>"
        "1. GH Actions logs — did the workflow error? "
        "2. Bitget rate limit / blocked HTTP status. "
        "3. Supabase auth or write cap. "
        "4. Runner queue depth."
        "</blockquote>"
    )
    footer = ""
    if actions_url:
        footer = f'\n<a href="{_e(actions_url)}">Actions log →</a>'
    return "\n\n".join([header, subtitle, body, causes]) + footer


def parser_drift_card(*, coin_names: list[str], drift_count: int,
                      observed_at: str) -> str:
    header = "🟡 <b>PARSER DRIFT</b>  ·  <i>data-quality alert</i>"
    subtitle = f"<i>{drift_count} row(s) tagged with non-complete data_quality</i>"
    rows = [
        ("Rows affected", str(drift_count)),
        ("Coins", ", ".join(coin_names[:6]) + (" …" if len(coin_names) > 6 else "")),
        ("Seen at", _fmt_ts(observed_at)),
    ]
    body = "🧪 <b>DETAILS</b>\n" + _kv_block(rows)
    guide = (
        "🧭 <b>WHAT THIS MEANS</b>\n<blockquote>"
        "Parser saw a Bitget shape it did not recognize. "
        "Investigate before Phase 2 labeling — a silent schema drift "
        "corrupts every downstream feature."
        "</blockquote>"
    )
    return "\n\n".join([header, subtitle, body, guide])
