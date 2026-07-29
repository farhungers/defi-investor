"""Seed venue_coin_map from authoritative Bitget + Binance spot symbol lists.

Reason: earn_events uses the coin symbol as reported by each venue's Earn
program (e.g. Bitget Earn ships 'PEPE' while Bitget spot lists both
'PEPEUSDT' and '1000PEPEUSDT'; Bitget Earn 'CAT' vs Bitget spot
'CATUSDT' vs '1000CATSUSDT'). The L2 capture daemon needs the exact
spot inst_id per venue.

Strategy:
1. Fetch authoritative symbol lists:
     Bitget: GET https://api.bitget.com/api/v2/spot/public/symbols
     Binance: GET https://api.binance.com/api/v3/exchangeInfo
2. Build a per-venue map: coin_name (baseCoin/baseAsset, upper) -> canonical
   inst_id (the venue's own symbol string).
3. For every earn_events coin, resolve the venue-specific inst_id:
     a. Try exact match on baseCoin.
     b. If no match and the coin name starts with a digit prefix like
        '1000', try mapping without the prefix (e.g. earn '1000CAT' ->
        maybe spot 'CAT' or 'CATS').
     c. Otherwise, no mapping; leave gap.
4. Upsert into venue_coin_map (skip rows where coin_name == inst_id
   without the USDT suffix — those match by string equality already).

Runs today. Idempotent.

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY
"""
from __future__ import annotations

import logging
import os
import sys
from typing import Optional

import httpx
from dotenv import load_dotenv
from supabase import create_client

from defi_investor.orderbook.universe import _absent_marker


LOG = logging.getLogger("defi_investor.seed_venue_coin_map")

BITGET_SYMBOLS_URL = "https://api.bitget.com/api/v2/spot/public/symbols"
BINANCE_EXCHANGE_INFO_URL = "https://api.binance.com/api/v3/exchangeInfo"

QUOTE = "USDT"


def _fetch_bitget_symbols(client: httpx.Client) -> dict[str, list[str]]:
    """Return {baseCoin: [full_symbol, ...]} for USDT-quoted symbols on Bitget."""
    r = client.get(BITGET_SYMBOLS_URL, timeout=30.0)
    r.raise_for_status()
    body = r.json()
    if body.get("code") != "00000":
        raise RuntimeError(f"bitget symbols error: {body}")
    out: dict[str, list[str]] = {}
    for row in body.get("data", []):
        quote = (row.get("quoteCoin") or "").upper()
        if quote != QUOTE:
            continue
        base = (row.get("baseCoin") or "").upper()
        symbol = (row.get("symbol") or "").upper()
        if base and symbol:
            out.setdefault(base, []).append(symbol)
    return out


def _fetch_binance_symbols(client: httpx.Client) -> dict[str, list[str]]:
    """Return {baseAsset: [full_symbol, ...]} for USDT-quoted symbols on Binance."""
    r = client.get(BINANCE_EXCHANGE_INFO_URL, timeout=30.0)
    r.raise_for_status()
    body = r.json()
    out: dict[str, list[str]] = {}
    for row in body.get("symbols", []):
        if row.get("status") != "TRADING":
            continue
        quote = (row.get("quoteAsset") or "").upper()
        if quote != QUOTE:
            continue
        base = (row.get("baseAsset") or "").upper()
        symbol = (row.get("symbol") or "").upper()
        if base and symbol:
            out.setdefault(base, []).append(symbol)
    return out


def _resolve_inst_id(coin: str, venue_map: dict[str, list[str]]) -> Optional[str]:
    """Look up the venue's authoritative spot inst_id for one earn coin.

    Returns None if the coin isn't listed on that venue.
    """
    coin = coin.upper().strip()
    # Direct match: baseCoin == coin
    if coin in venue_map:
        symbols = venue_map[coin]
        # Prefer f"{coin}USDT" if present; else first available
        target = f"{coin}{QUOTE}"
        if target in symbols:
            return target
        return symbols[0]

    # Numeric-prefix aliases: earn '1000CAT' -> spot 'CATS' (with the
    # prefix + plural variant). Try stripping common prefixes.
    for prefix in ("1000", "10000", "1M"):
        if coin.startswith(prefix):
            stripped = coin[len(prefix):]
            if stripped in venue_map:
                # Return the venue's own symbol string, which likely includes
                # the prefix (e.g. Bitget: 1000PEPEUSDT).
                symbols = venue_map[stripped]
                # Prefer symbols that contain the original prefix
                prefixed = [s for s in symbols if s.startswith(prefix)]
                if prefixed:
                    return prefixed[0]
                return symbols[0]

    return None


def _load_earn_coins(sb) -> list[str]:
    """Distinct coin_names across all venues in earn_events."""
    r = sb.table("earn_events").select("coin_name").execute()
    coins = {(row.get("coin_name") or "").upper().strip() for row in (r.data or [])}
    coins.discard("")
    return sorted(coins)


def _upsert_map(sb, rows: list[dict]) -> int:
    if not rows:
        return 0
    n = 0
    BATCH = 500
    for start in range(0, len(rows), BATCH):
        batch = rows[start:start + BATCH]
        (
            sb.table("venue_coin_map")
            .upsert(batch, on_conflict="venue,venue_coin")
            .execute()
        )
        n += len(batch)
    return n


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

    with httpx.Client(headers={"User-Agent": "defi-investor-research/0.3.0"}) as client:
        LOG.info("fetching Bitget spot symbols…")
        bitget_map = _fetch_bitget_symbols(client)
        LOG.info("Bitget USDT-quoted bases: %d", len(bitget_map))

        LOG.info("fetching Binance spot symbols…")
        binance_map = _fetch_binance_symbols(client)
        LOG.info("Binance USDT-quoted bases: %d", len(binance_map))

    earn_coins = _load_earn_coins(sb)
    LOG.info("earn_events distinct coins: %d", len(earn_coins))

    to_upsert: list[dict] = []
    stats = {
        "bitget_direct": 0, "bitget_prefix_alias": 0, "bitget_absent": 0,
        "binance_direct": 0, "binance_prefix_alias": 0, "binance_absent": 0,
    }

    for coin in earn_coins:
        # Bitget
        bitget_inst = _resolve_inst_id(coin, bitget_map)
        if bitget_inst is None:
            stats["bitget_absent"] += 1
            to_upsert.append({
                "canonical_coin": coin,
                "venue": "bitget",
                "venue_coin": _absent_marker(coin),
                "notes": f"no bitget spot counterpart for earn coin={coin}",
            })
        elif bitget_inst == f"{coin}{QUOTE}":
            stats["bitget_direct"] += 1
            # No row needed — string equality already works. Skip upsert.
        else:
            stats["bitget_prefix_alias"] += 1
            to_upsert.append({
                "canonical_coin": coin,
                "venue": "bitget",
                "venue_coin": bitget_inst,
                "notes": f"prefix-alias resolved from earn coin={coin}",
            })

        # Binance
        binance_inst = _resolve_inst_id(coin, binance_map)
        if binance_inst is None:
            stats["binance_absent"] += 1
            to_upsert.append({
                "canonical_coin": coin,
                "venue": "binance",
                "venue_coin": _absent_marker(coin),
                "notes": f"no binance spot counterpart for earn coin={coin}",
            })
        elif binance_inst == f"{coin}{QUOTE}":
            stats["binance_direct"] += 1
        else:
            stats["binance_prefix_alias"] += 1
            to_upsert.append({
                "canonical_coin": coin,
                "venue": "binance",
                "venue_coin": binance_inst,
                "notes": f"prefix-alias resolved from earn coin={coin}",
            })

    n_written = _upsert_map(sb, to_upsert)
    LOG.info("venue_coin_map upserted: %d rows", n_written)
    LOG.info("stats: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
