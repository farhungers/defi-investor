"""Bitget spot-listings scraper for the METHOD §1.4 control arm.

Endpoint (verified 2026-07-11):

    GET https://api.bitget.com/api/v2/spot/public/symbols

Response shape:

    {"code":"00000","msg":"success","requestTime":...,
     "data":[
        {"symbol":"GOATUSDT","baseCoin":"GOAT","quoteCoin":"USDT",
         "status":"online","openTime":"1729314000000","offTime":"", ...},
        ...
     ]}

`openTime` is epoch ms when the pair went live for spot trading — the
authoritative listing timestamp. `offTime` is populated for delisted
pairs. We take one snapshot per day (see scraper wiring), upsert on
`symbol`, and preserve `first_seen_at` on repeat rows so we know when
*our* observation began (separate from the on-chain listing timestamp).

Compared to parsing the announcements API this endpoint is:
- Authoritative (no regex against a human-readable title).
- Complete (all 1000+ pairs in one call, not paginated by date).
- Stable (same shape as Bitget's other v2 public market endpoints).

The one thing it does *not* give: perp listings. USDT-M perp symbols are
served by `/api/v2/mix/market/contracts?productType=USDT-FUTURES`. Phase 2
only needs spot for the control arm — perp add-on is a follow-up.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx


LOG = logging.getLogger("defi_investor.bitget_listings")

SYMBOLS_URL = "https://api.bitget.com/api/v2/spot/public/symbols"
USER_AGENT = "defi-investor-research/0.2.1 (Bitget Earn hypothesis test)"


@dataclass(frozen=True)
class BitgetListing:
    """One spot-pair listing row, ready to persist."""
    symbol: str            # e.g. 'GOATUSDT'
    coin_name: str         # baseCoin, uppercase
    quote_coin: str        # USDT / USDC / ...
    listing_ts: str        # ISO 8601 UTC, from Bitget openTime
    status: str            # 'online' | 'offline' | other
    off_ts: Optional[str]  # ISO 8601 UTC, from Bitget offTime (empty → None)

    def to_row(self, *, first_seen_at: str, last_seen_at: str) -> dict:
        return {
            "symbol": self.symbol,
            "coin_name": self.coin_name,
            "quote_coin": self.quote_coin,
            "listing_ts": self.listing_ts,
            "status": self.status,
            "off_ts": self.off_ts,
            "first_seen_at": first_seen_at,
            "last_seen_at": last_seen_at,
            "snapshot_source": "spot_symbols",
        }


def _ms_to_iso(ms_str: str) -> Optional[str]:
    """Bitget returns numeric fields as strings. Empty string → None."""
    if not ms_str:
        return None
    try:
        ms = int(ms_str)
    except (ValueError, TypeError):
        return None
    if ms <= 0:
        return None
    return datetime.fromtimestamp(ms / 1000.0, tz=timezone.utc).isoformat()


def parse_symbol(entry: dict) -> Optional[BitgetListing]:
    """Turn one Bitget symbol entry into a `BitgetListing`. Skip malformed."""
    symbol = entry.get("symbol")
    base = entry.get("baseCoin")
    quote = entry.get("quoteCoin")
    listing_iso = _ms_to_iso(entry.get("openTime", ""))
    if not symbol or not base or not quote or listing_iso is None:
        return None
    return BitgetListing(
        symbol=symbol,
        coin_name=base.upper(),
        quote_coin=quote.upper(),
        listing_ts=listing_iso,
        status=entry.get("status") or "unknown",
        off_ts=_ms_to_iso(entry.get("offTime", "")),
    )


def fetch_spot_symbols(*, client: Optional[httpx.Client] = None) -> tuple[list[BitgetListing], int, Optional[str]]:
    """Fetch all Bitget spot symbols. Returns (listings, http_status, error).

    Never raises. On any failure returns `([], status, error_str)`.
    """
    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=20.0,
        )
    try:
        try:
            r = client.get(SYMBOLS_URL)
        except httpx.HTTPError as e:
            return [], 0, f"http_error: {e}"
        if r.status_code != 200:
            return [], r.status_code, f"non_200: {r.text[:200]}"
        try:
            body = r.json()
        except ValueError:
            return [], r.status_code, "invalid_json"
        if body.get("code") != "00000":
            return [], r.status_code, f"api_code={body.get('code')} msg={body.get('msg')}"
        data = body.get("data") or []
        listings: list[BitgetListing] = []
        for entry in data:
            listing = parse_symbol(entry)
            if listing is not None:
                listings.append(listing)
        return listings, r.status_code, None
    finally:
        if close_after:
            client.close()


def snapshot_listings(
    *,
    observed_at: str,
    client: Optional[httpx.Client] = None,
) -> tuple[list[BitgetListing], dict]:
    """One-shot snapshot for the daily control-arm scrape.

    Returns (listings, stats_dict). Stats fields:
      - `n_fetched`: total symbols parsed
      - `n_online`, `n_offline`: status breakdown
      - `n_usdt_quoted`: relevant subset for our hypothesis
      - `error`: parseable error string or None
    """
    listings, status, err = fetch_spot_symbols(client=client)
    stats = {
        "n_fetched": len(listings),
        "n_online": sum(1 for l in listings if l.status == "online"),
        "n_offline": sum(1 for l in listings if l.status == "offline"),
        "n_usdt_quoted": sum(1 for l in listings if l.quote_coin == "USDT"),
        "http_status": status,
        "error": err,
    }
    LOG.info("bitget_listings snapshot: %s", stats)
    return listings, stats
