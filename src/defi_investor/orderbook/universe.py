"""L2 capture universe manager.

Decides which coins the WS clients should subscribe to. Rules
per docs/ORDERBOOK_DESIGN.md §Universe scoping:

  1. Coins with any active Bitget Earn product (product_id present in
     earn_events where sold_out=False AND venue='bitget').
  2. Plus coins whose most-recent Earn program (any venue) was seen
     within the past `RECENT_WINDOW_DAYS` (default 30).
  3. Union produces the candidate coin set.

Each coin is converted to a per-venue inst_id via `coin_to_symbol`
(e.g. `BTC` -> `BTCUSDT`). Callers that need only one venue can filter.

Optionally cross-checks against `bitget_listings` to confirm the coin
trades on Bitget spot, so we don't subscribe to inst_ids that would
just error on the WS.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Optional


LOG = logging.getLogger("defi_investor.orderbook.universe")


RECENT_WINDOW_DAYS = 30
DEFAULT_QUOTE = "USDT"


@dataclass(frozen=True)
class UniverseEntry:
    coin_name: str
    bitget_inst_id: Optional[str]    # None if coin is not listed on Bitget spot
    binance_inst_id: Optional[str]   # None if coin is not listed on Binance spot
    reason: str                      # 'active_earn' | 'recent_earn'


def build_universe(
    sb,
    *,
    recent_window_days: int = RECENT_WINDOW_DAYS,
    quote: str = DEFAULT_QUOTE,
    filter_bitget_listed: bool = True,
    now_utc: Optional[datetime] = None,
    coin_map_overrides: Optional[dict[tuple[str, str], str]] = None,
) -> list[UniverseEntry]:
    """Query Supabase and return the current L2 capture universe.

    `filter_bitget_listed`: when True, drop coins that don't appear in
    `bitget_listings` with status='online'. This avoids trying to
    subscribe to WS streams that would error. Skip if bitget_listings is
    unreliable at your snapshot moment.
    """
    now = now_utc or datetime.now(timezone.utc)
    recent_cutoff = (now - timedelta(days=recent_window_days)).isoformat()

    # 1. Active-earn coins across all venues
    active_earn: dict[str, str] = {}  # coin_name -> reason
    try:
        r_active = (
            sb.table("earn_events")
            .select("coin_name")
            .eq("sold_out", False)
            .execute()
        )
        for row in r_active.data or []:
            coin = _norm_coin(row.get("coin_name"))
            if coin:
                active_earn[coin] = "active_earn"
    except Exception as e:  # noqa: BLE001
        LOG.warning("active earn query failed: %s", e)

    # 2. Recent-earn coins (past RECENT_WINDOW_DAYS by last_seen_at)
    recent_earn: dict[str, str] = {}
    try:
        r_recent = (
            sb.table("earn_events")
            .select("coin_name,last_seen_at")
            .gte("last_seen_at", recent_cutoff)
            .execute()
        )
        for row in r_recent.data or []:
            coin = _norm_coin(row.get("coin_name"))
            if coin and coin not in active_earn:
                recent_earn[coin] = "recent_earn"
    except Exception as e:  # noqa: BLE001
        LOG.warning("recent earn query failed: %s", e)

    # 3. Bitget-listed filter (optional). Skips the filter if the
    # bitget_listings table is empty — otherwise we'd drop everything
    # when the listings scraper hasn't populated yet.
    bitget_listed: Optional[set[str]] = None
    if filter_bitget_listed:
        try:
            r_list = (
                sb.table("bitget_listings")
                .select("coin_name")
                .eq("status", "online")
                .execute()
            )
            candidate = {
                _norm_coin(row.get("coin_name"))
                for row in (r_list.data or [])
                if row.get("coin_name")
            }
            candidate.discard(None)  # type: ignore[arg-type]
            if candidate:
                bitget_listed = candidate
            else:
                LOG.warning(
                    "bitget_listings has 0 online rows; skipping listing filter "
                    "(daily listings scraper may not have run yet)"
                )
        except Exception as e:  # noqa: BLE001
            LOG.warning("bitget_listings query failed; skipping filter: %s", e)

    # 4. Coin-map overrides for venues where the earn name differs from the
    # spot inst_id (e.g. earn '1000CAT' vs Bitget spot '1000CATSUSDT').
    # `coin_map_overrides` is keyed by (venue, canonical_coin) -> venue-specific inst_id.
    if coin_map_overrides is None:
        coin_map_overrides = _fetch_coin_map_overrides(sb)

    all_coins = {**active_earn, **recent_earn}
    out: list[UniverseEntry] = []
    for coin, reason in sorted(all_coins.items()):
        if bitget_listed is not None and coin not in bitget_listed:
            continue
        bitget_inst = coin_map_overrides.get(("bitget", coin), f"{coin}{quote}")
        binance_inst = coin_map_overrides.get(("binance", coin), f"{coin}{quote}")
        out.append(UniverseEntry(
            coin_name=coin,
            bitget_inst_id=bitget_inst,
            binance_inst_id=binance_inst,
            reason=reason,
        ))

    LOG.info(
        "universe: %d coins (%d active_earn, %d recent_earn) after listing filter=%s",
        len(out),
        sum(1 for e in out if e.reason == "active_earn"),
        sum(1 for e in out if e.reason == "recent_earn"),
        filter_bitget_listed,
    )
    return out


def _fetch_coin_map_overrides(sb) -> dict[tuple[str, str], str]:
    """Read venue_coin_map. Returns {(venue, canonical_coin): venue_coin_inst_id}."""
    try:
        r = sb.table("venue_coin_map").select("*").execute()
    except Exception as e:  # noqa: BLE001
        LOG.warning("venue_coin_map query failed; using string-equality only: %s", e)
        return {}
    out: dict[tuple[str, str], str] = {}
    for row in r.data or []:
        v = (row.get("venue") or "").strip().lower()
        canonical = _norm_coin(row.get("canonical_coin"))
        venue_coin = (row.get("venue_coin") or "").strip().upper()
        if v and canonical and venue_coin:
            out[(v, canonical)] = venue_coin
    return out


def _norm_coin(v) -> Optional[str]:
    if v is None:
        return None
    s = str(v).strip().upper()
    if not s:
        return None
    # Drop suffixes like '.USDT' just in case some rows carry them
    return s.replace(".USDT", "").replace("-USDT", "")
