"""HTML card formatters for Telegram alerts.

Telegram HTML mode accepts: <b> <i> <u> <s> <code> <pre> <a href> and \\n.
Everything else must be HTML-escaped. Each formatter returns a self-contained
message body ready to hand to sendMessage with parse_mode=HTML.

Design intent (per user preference): "very amazing visually beautiful cards,
easy to understand and complete". Layout:

- Emoji + bold title on first line (event type + coin + family).
- Aligned key/value block using code fences so mono width holds columns.
- One-line context (why we're pinging).
- Provenance footer (product id, scrape sha256 head).

None of these are trading signals. They're operational + interesting-event
notifications during the Phase 1 pilot.
"""
from __future__ import annotations

import html
from datetime import datetime, timezone
from typing import Optional

from .models import EarnEvent


# ---------- helpers --------------------------------------------------------

def _e(s: object) -> str:
    """HTML-escape any object stringified."""
    return html.escape("" if s is None else str(s), quote=False)


def _fmt_apy(v: Optional[float]) -> str:
    if v is None:
        return "—"
    if v >= 100:
        return f"{v:,.0f}%"
    return f"{v:,.2f}%"


def _fmt_amount(v: Optional[float], coin: str) -> str:
    if v is None:
        return "—"
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


def _days_since(iso: Optional[str], now: Optional[datetime] = None) -> Optional[int]:
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        n = now or datetime.now(timezone.utc)
        return max(0, (n - dt).days)
    except (ValueError, TypeError):
        return None


def _tier_summary(ev: EarnEvent) -> str:
    """One-line tier structure. e.g. 'single-tier' or 'ladder: 6.16% → 1.50%'."""
    tiers = ev.tiers or []
    if not tiers:
        return "no tiers"
    if len(tiers) == 1:
        return "single-tier"
    apys = [t.get("apy", "?") for t in tiers]
    return f"{len(tiers)}-tier ladder: " + " → ".join(f"{a}%" for a in apys)


def _kv_block(rows: list[tuple[str, str]]) -> str:
    """Fixed-width key/value block, wrapped in <pre> so alignment survives.

    Longest key + 2 spaces + value.
    """
    if not rows:
        return ""
    label_w = max(len(k) for k, _ in rows)
    lines = [f"{k.ljust(label_w)}  {v}" for k, v in rows]
    return "<pre>" + _e("\n".join(lines)) + "</pre>"


# ---------- cards ----------------------------------------------------------

def sold_out_card(ev: EarnEvent, *, observed_at: str) -> str:
    """Fires on a 2 → 6 (or *→6) transition."""
    days_open = _days_since(ev.start_time, now=_parse_iso(observed_at))
    rows = [
        ("APR", _fmt_apy(ev.max_apy)),
        ("Per-user cap", _fmt_amount(ev.per_user_cap_underlying, ev.coin_name)),
        ("Structure", _tier_summary(ev)),
        ("Opened", _fmt_ts(ev.start_time) + (f" ({days_open}d ago)" if days_open is not None else "")),
        ("Family", _e(ev.second_biz_line)),
    ]
    title = f"🔴 <b>Sold out — {_e(ev.coin_name)} {_e(ev.second_biz_line)}</b>"
    footer = (
        f"<i>status → 6, seen at {_fmt_ts(observed_at)}</i>\n"
        f"<code>{_e(ev.product_id)}</code>"
    )
    return f"{title}\n\n{_kv_block(rows)}\n{footer}"


def reopened_card(ev: EarnEvent, *, observed_at: str) -> str:
    """Fires on a 6 → 2 transition. Unusual, always worth a card."""
    rows = [
        ("APR", _fmt_apy(ev.max_apy)),
        ("Per-user cap", _fmt_amount(ev.per_user_cap_underlying, ev.coin_name)),
        ("Structure", _tier_summary(ev)),
        ("Family", _e(ev.second_biz_line)),
    ]
    title = f"🟢 <b>Re-opened — {_e(ev.coin_name)} {_e(ev.second_biz_line)}</b>"
    footer = (
        f"<i>status 6 → 2 at {_fmt_ts(observed_at)} (unusual)</i>\n"
        f"<code>{_e(ev.product_id)}</code>"
    )
    return f"{title}\n\n{_kv_block(rows)}\n{footer}"


def new_listing_card(ev: EarnEvent, *, observed_at: str) -> str:
    """First time we've seen this product_id in the catalog."""
    rows = [
        ("APR", _fmt_apy(ev.max_apy)),
        ("Per-user cap", _fmt_amount(ev.per_user_cap_underlying, ev.coin_name)),
        ("Structure", _tier_summary(ev)),
        ("Started", _fmt_ts(ev.start_time)),
        ("Family", _e(ev.second_biz_line)),
    ]
    title = f"🆕 <b>New listing — {_e(ev.coin_name)} {_e(ev.second_biz_line)}</b>"
    footer = (
        f"<i>first seen at {_fmt_ts(observed_at)}</i>\n"
        f"<code>{_e(ev.product_id)}</code>"
    )
    return f"{title}\n\n{_kv_block(rows)}\n{footer}"


def stall_card(*, last_scrape_at: str, minutes_ago: int, threshold_min: int,
               actions_url: Optional[str] = None) -> str:
    """Cadence gap alert. Sent by the health workflow."""
    rows = [
        ("Last scrape", _fmt_ts(last_scrape_at) + f" ({minutes_ago}m ago)"),
        ("Threshold", f"{threshold_min} min"),
        ("Expected", "every 15 min"),
    ]
    title = "⚠️ <b>Scraper stall</b>"
    footer = ""
    if actions_url:
        footer = f'\n<a href="{_e(actions_url)}">Actions log →</a>'
    return f"{title}\n\n{_kv_block(rows)}{footer}"


def parser_drift_card(*, coin_names: list[str], drift_count: int,
                      observed_at: str) -> str:
    """Fires when parser flags data_quality != 'complete' on any recent row."""
    rows = [
        ("Rows affected", str(drift_count)),
        ("Coins", ", ".join(coin_names[:6]) + (" …" if len(coin_names) > 6 else "")),
        ("Seen at", _fmt_ts(observed_at)),
    ]
    title = "🟡 <b>Parser drift detected</b>"
    footer = "<i>investigate before the next migration</i>"
    return f"{title}\n\n{_kv_block(rows)}\n{footer}"


# ---------- utilities ------------------------------------------------------

def _parse_iso(iso: Optional[str]) -> Optional[datetime]:
    if not iso:
        return None
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None
