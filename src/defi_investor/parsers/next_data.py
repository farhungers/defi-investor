"""Parse the __NEXT_DATA__ blob from https://www.bitget.com/asia/earning.

Design:
- Deterministic: same raw HTML in produces the same events out.
- Provenance is filled by the caller (scraper). Parser only reads content.
- Supports listData + hotData + structuralList in one pass to dedupe by product_id.
- Ignores unknown secondBizLine values but tags them as schema_drift for review.
"""
from __future__ import annotations

import json
import re
from typing import Iterable, Iterator, Optional

from ..models import EarnEvent, _epoch_ms_to_iso, parse_apy, parse_max_step


NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json"[^>]*>(.+?)</script>',
    re.DOTALL,
)

# Product families we know how to emit events for.
# Trend and SharkFin have different structure and are deferred to Phase 2.
# OnChainElite added 2026-07-28 after a BGBTC record surfaced from hotData with
# this biz_line. Record shape parses cleanly (single APY, empty tiers, no cap),
# so accepted as first-class. If future OnChainElite records prove structurally
# different, revisit and consider a separate parser path.
LIST_DATA_BIZLINES = {
    "Savings",
    "PosStaking",
    "CashPlus",
    "FundMarket",
    "OnChainElite",
}


class ParseError(Exception):
    pass


def extract_next_data(html: str) -> dict:
    """Locate the __NEXT_DATA__ JSON blob in a Bitget earning page HTML."""
    m = NEXT_DATA_RE.search(html)
    if not m:
        raise ParseError("__NEXT_DATA__ script tag not found")
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError as e:
        raise ParseError(f"__NEXT_DATA__ JSON parse failed: {e}") from e


def parse_earning_page(html: str) -> list[EarnEvent]:
    """Return one EarnEvent per unique product_id observed in the page.

    Sources in preference order (first source seen wins fields):
      1. listData (grouped by coin, full detail)
      2. hotData (featured; may have fields listData missed)
    """
    blob = extract_next_data(html)
    try:
        page_props = blob["props"]["pageProps"]
    except KeyError as e:
        raise ParseError(f"expected NEXT_DATA['props']['pageProps'], missing {e}") from e

    seen: dict[str, EarnEvent] = {}

    for ev in _iter_list_data(page_props.get("listData", [])):
        if ev.product_id not in seen:
            seen[ev.product_id] = ev

    for ev in _iter_hot_data(page_props.get("hotData", [])):
        if ev.product_id not in seen:
            seen[ev.product_id] = ev

    return list(seen.values())


def _iter_list_data(list_data: Iterable[dict]) -> Iterator[EarnEvent]:
    for coin_row in list_data or []:
        if not isinstance(coin_row, dict):
            continue
        for biz_group in coin_row.get("bizLineProductList", []) or []:
            if not isinstance(biz_group, dict):
                continue
            for prod in biz_group.get("productList", []) or []:
                ev = _product_to_event(prod, source="listData")
                if ev is not None:
                    yield ev


def _iter_hot_data(hot_data: Iterable[dict]) -> Iterator[EarnEvent]:
    for prod in hot_data or []:
        ev = _product_to_event(prod, source="hotData")
        if ev is not None:
            yield ev


def _product_to_event(prod: dict, *, source: str) -> Optional[EarnEvent]:
    if not isinstance(prod, dict):
        return None

    # Product identity: prefer `id` (listData), fall back to `productId` (hotData).
    product_id = prod.get("id") or prod.get("productId")
    coin_name = prod.get("coinName")
    biz_line = prod.get("secondBizLine")

    if not product_id or not coin_name or not biz_line:
        return None

    notes: list[str] = []
    data_quality = "complete"

    if biz_line not in LIST_DATA_BIZLINES:
        notes.append(f"schema_drift: unknown secondBizLine={biz_line!r} from source={source}")
        data_quality = "schema_drift"

    status_raw = prod.get("status")
    status = int(status_raw) if isinstance(status_raw, (int, float)) else None

    raw_apy_list = prod.get("apyList") or []
    tiers = [t for t in raw_apy_list if isinstance(t, dict)]

    return EarnEvent(
        product_id=str(product_id),
        coin_name=str(coin_name),
        second_biz_line=str(biz_line),
        max_apy=parse_apy(prod.get("maxApy")),
        min_apy=parse_apy(prod.get("minApy")),
        per_user_cap_underlying=parse_max_step(prod.get("apyList")),
        tiers=tiers,
        start_time=_epoch_ms_to_iso(prod.get("startTime")),
        period_days=_coerce_int(prod.get("period")),
        lock_model=bool(prod["lockModel"]) if "lockModel" in prod else None,
        period_type=_coerce_int(prod.get("periodType")),
        status=status,
        sold_out=(status == 6) if status is not None else None,
        data_quality=data_quality,
        notes=notes,
    )


def _coerce_int(v: object) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        try:
            return int(v)
        except ValueError:
            return None
    return None
