"""Bitget perp open-interest snapshot fetcher (Phase 2 confound support).

Bitget's V2 public API exposes CURRENT open interest only. There is no
historical endpoint. To make METHOD §1.3's confound tag
`perp_oi_pct_change_prior_24h` computable at label time we snapshot OI on
the same 15-min cron as the scraper, persist it, and derive the 24h delta
from the accumulated table.

Endpoint (verified 2026-07-11):

    GET https://api.bitget.com/api/v2/mix/market/open-interest
    Params:
        symbol       e.g. LABUSDT
        productType  USDT-FUTURES

Response shape:

    {"code":"00000","msg":"success","requestTime":...,
     "data":{"openInterestList":[{"symbol":"LABUSDT","size":"10265697"}],
             "ts":"1783..."}}

`size` is in base-asset units (LAB, not USDT). For the confound we only
need the fractional change, so base units are sufficient. USD notional
would require joining a mark-price snapshot.

Symbols with no perp listing return `code=40034` and are recorded as
`market='none', oi_base=NULL`. This preserves the snapshot cadence
(gap-free rows) so the confound query can distinguish "no perp market"
from "cron missed a run" downstream.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Optional

import httpx


LOG = logging.getLogger("defi_investor.oi_snapshots")

OI_URL = "https://api.bitget.com/api/v2/mix/market/open-interest"
PRODUCT_TYPE = "USDT-FUTURES"
USER_AGENT = "defi-investor-research/0.2.1 (Bitget Earn hypothesis test)"

# Between-call pacing. Bitget public market endpoints are documented at
# 20 req/s per IP but we run this alongside the scraper's own calls, so
# stay conservative.
_INTER_CALL_SLEEP_S = 0.10

# Snapshot job soft cap so a big catalog cannot blow past the 5-min GH
# Actions timeout. 300 coins x 0.1s pacing + ~0.2s request each ≈ 90s.
_MAX_COINS_PER_RUN = 300


@dataclass(frozen=True)
class OISnapshot:
    """One coin's OI reading, ready to persist."""
    coin_name: str
    snapped_at: str          # ISO 8601 UTC
    symbol: str
    market: str              # 'perp' | 'none'
    oi_base: Optional[float]
    http_status: int
    error: Optional[str] = None

    def to_row(self) -> dict:
        return {
            "coin_name": self.coin_name,
            "snapped_at": self.snapped_at,
            "symbol": self.symbol,
            "market": self.market,
            "oi_base": self.oi_base,
            "http_status": self.http_status,
            "error": self.error,
        }


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def fetch_current_oi(
    coin_name: str,
    *,
    snapped_at: Optional[str] = None,
    client: Optional[httpx.Client] = None,
) -> OISnapshot:
    """Fetch one coin's current perp OI. Never raises.

    `snapped_at` is the timestamp attached to the resulting row. Passing
    the caller's batch timestamp keeps a whole snapshot cycle aligned to
    a single wall-clock value, which simplifies the anchor-time query.
    Defaults to now() at call time.
    """
    ts = snapped_at or _now_iso()
    symbol = f"{coin_name.upper()}USDT"
    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10.0,
        )
    try:
        try:
            r = client.get(OI_URL, params={
                "symbol": symbol, "productType": PRODUCT_TYPE,
            })
        except httpx.HTTPError as e:
            return OISnapshot(
                coin_name=coin_name, snapped_at=ts, symbol=symbol,
                market="none", oi_base=None,
                http_status=0, error=f"http_error: {e}",
            )
        status = r.status_code
        if status != 200:
            return OISnapshot(
                coin_name=coin_name, snapped_at=ts, symbol=symbol,
                market="none", oi_base=None,
                http_status=status, error=f"non_200: {r.text[:200]}",
            )
        try:
            body = r.json()
        except ValueError:
            return OISnapshot(
                coin_name=coin_name, snapped_at=ts, symbol=symbol,
                market="none", oi_base=None,
                http_status=status, error="invalid_json",
            )
        code = body.get("code")
        if code != "00000":
            # 40034 = symbol doesn't exist as a perp. Not an error for our
            # purposes; record the gap-free row and move on.
            return OISnapshot(
                coin_name=coin_name, snapped_at=ts, symbol=symbol,
                market="none", oi_base=None,
                http_status=status,
                error=f"api_code={code} msg={body.get('msg')}",
            )
        data = body.get("data") or {}
        oi_list = data.get("openInterestList") or []
        if not oi_list:
            return OISnapshot(
                coin_name=coin_name, snapped_at=ts, symbol=symbol,
                market="perp", oi_base=None,
                http_status=status, error="empty_openInterestList",
            )
        try:
            size = float(oi_list[0].get("size"))
        except (TypeError, ValueError):
            return OISnapshot(
                coin_name=coin_name, snapped_at=ts, symbol=symbol,
                market="perp", oi_base=None,
                http_status=status, error="unparsable_size",
            )
        return OISnapshot(
            coin_name=coin_name, snapped_at=ts, symbol=symbol,
            market="perp", oi_base=size,
            http_status=status, error=None,
        )
    finally:
        if close_after:
            client.close()


def snapshot_universe(
    coin_names: Iterable[str],
    *,
    snapped_at: Optional[str] = None,
    client: Optional[httpx.Client] = None,
    max_coins: int = _MAX_COINS_PER_RUN,
    inter_call_sleep_s: float = _INTER_CALL_SLEEP_S,
) -> list[OISnapshot]:
    """Snapshot OI for every distinct coin in the universe.

    Uses a single shared timestamp for the whole batch so downstream
    queries can pivot the cadence cleanly. Sleeps between calls to stay
    well under Bitget's documented rate limit.
    """
    ts = snapped_at or _now_iso()
    # De-dup, preserve order for determinism in logs.
    seen: set[str] = set()
    ordered: list[str] = []
    for c in coin_names:
        if not c:
            continue
        u = c.upper()
        if u in seen:
            continue
        seen.add(u)
        ordered.append(u)

    if len(ordered) > max_coins:
        LOG.warning("snapshot_universe: %d coins exceeds cap %d; truncating",
                    len(ordered), max_coins)
        ordered = ordered[:max_coins]

    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=10.0,
        )
    out: list[OISnapshot] = []
    try:
        for i, coin in enumerate(ordered):
            snap = fetch_current_oi(coin, snapped_at=ts, client=client)
            out.append(snap)
            if i + 1 < len(ordered) and inter_call_sleep_s > 0:
                time.sleep(inter_call_sleep_s)
        n_ok = sum(1 for s in out if s.oi_base is not None)
        LOG.info("snapshot_universe: %d/%d coins with perp OI at %s",
                 n_ok, len(out), ts)
        return out
    finally:
        if close_after:
            client.close()
