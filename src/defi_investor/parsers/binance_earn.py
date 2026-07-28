"""Parse the Binance Simple Earn homepage API response.

Endpoint: GET https://www.binance.com/bapi/earn/v1/friendly/finance-earn/simple-earn/homepage/details
Query params: pageIndex (1-based), pageSize (<= 50 observed)
Response envelope: {"code": "000000", "success": true, "data": {"total": "<N>", "list": [<product>, ...]}}

Rendering note: this is the "homepage" curated view. It appears to only list
currently-available products (sellOut is False on every observed row). Sold-out
detection is therefore diff-based upstream (a product_id that vanishes between
consecutive scrapes = sold_out event), same semantic model Bitget uses even
though Bitget also carries an explicit status=6 flag.

Design mirrors parsers/next_data.py:
- Deterministic; same JSON in → same events out.
- Provenance (raw_capture_*, first_seen_at) is filled by the caller.
- Returns list[EarnEvent] with venue='binance' pre-set.

APY unit normalization: Binance ships APY as decimal fraction (e.g. "0.06684390"
means 6.684% APR). Downstream code (notifier MIN_APR_FOR_ALERT, features) treats
event.max_apy as percentage-points, matching Bitget's wire format. We multiply
by 100 at parse time so venues share one unit.
"""
from __future__ import annotations

from typing import Iterable, Iterator, Optional

from ..models import EarnEvent


VENUE = "binance"

# Binance Simple Earn productType values we accept as first-class.
# LENDING_FLEXIBLE  → flexible savings
# LENDING_ACTIVITY  → limited-quota promo (very common for new listings, HIGH signal value)
# STAKING           → PoS staking (locked)
KNOWN_PRODUCT_TYPES = {
    "LENDING_FLEXIBLE",
    "LENDING_ACTIVITY",
    "STAKING",
}


class ParseError(Exception):
    pass


def parse_homepage_response(response_json: dict) -> list[EarnEvent]:
    """Parse one page of Binance Simple Earn homepage/details response.

    The caller is responsible for pagination (envelope carries `data.total`).
    Returns one EarnEvent per productId in this page. Duplicate productIds
    across pages are the caller's problem to dedupe.
    """
    if not isinstance(response_json, dict):
        raise ParseError(f"expected dict envelope, got {type(response_json).__name__}")

    if response_json.get("code") != "000000":
        raise ParseError(
            f"Binance API returned non-success code={response_json.get('code')!r} "
            f"message={response_json.get('message')!r}"
        )

    data = response_json.get("data")
    if not isinstance(data, dict):
        raise ParseError("envelope missing 'data' object")

    lst = data.get("list")
    if not isinstance(lst, list):
        raise ParseError("envelope 'data' missing 'list' array")

    return [ev for ev in _iter_products(lst) if ev is not None]


def _iter_products(products: Iterable[dict]) -> Iterator[Optional[EarnEvent]]:
    for prod in products:
        yield _product_to_event(prod)


def _product_to_event(prod: dict) -> Optional[EarnEvent]:
    if not isinstance(prod, dict):
        return None

    product_id = prod.get("productId")
    asset = prod.get("asset")
    if not product_id or not asset:
        return None

    detail_list = prod.get("productDetailList") or []
    first_detail = detail_list[0] if detail_list and isinstance(detail_list[0], dict) else {}
    product_type = first_detail.get("productType", "UNKNOWN")

    notes: list[str] = []
    data_quality = "complete"
    if product_type not in KNOWN_PRODUCT_TYPES:
        notes.append(
            f"schema_drift: unknown productType={product_type!r} for {product_id}"
        )
        data_quality = "schema_drift"

    duration_raw = prod.get("duration")
    duration_days = _coerce_int(duration_raw)
    lock_model = duration_days is not None and duration_days > 0

    max_apy_pct = _apy_decimal_to_pct(prod.get("highestApy"))
    apy_range = prod.get("apyRange") or []
    min_apy_pct: Optional[float] = None
    if isinstance(apy_range, list) and apy_range:
        parsed = [_apy_decimal_to_pct(x) for x in apy_range]
        parsed = [x for x in parsed if x is not None]
        if parsed:
            min_apy_pct = min(parsed)
            max_apy_pct = max(parsed) if max_apy_pct is None else max(max_apy_pct, max(parsed))

    per_user_cap = _parse_per_user_cap(first_detail)

    tiers = _extract_tiers(first_detail, prod.get("hasTierApy", False))

    return EarnEvent(
        product_id=str(product_id),
        coin_name=str(asset).upper(),
        second_biz_line=product_type,
        venue=VENUE,
        max_apy=max_apy_pct,
        min_apy=min_apy_pct,
        per_user_cap_underlying=per_user_cap,
        tiers=tiers,
        start_time=None,  # not exposed on the homepage endpoint
        period_days=duration_days if duration_days and duration_days > 0 else None,
        lock_model=lock_model,
        period_type=None,
        status=None,     # Binance homepage view doesn't ship a numeric status; sold_out is the signal
        sold_out=bool(prod.get("sellOut", False)),
        data_quality=data_quality,
        notes=notes,
    )


def _apy_decimal_to_pct(raw: object) -> Optional[float]:
    """Convert Binance's decimal-fraction APY ('0.06684390') to percentage (6.68439)."""
    if raw is None or raw == "":
        return None
    try:
        return float(raw) * 100.0
    except (TypeError, ValueError):
        return None


def _coerce_int(v: object) -> Optional[int]:
    if v is None:
        return None
    if isinstance(v, bool):
        return int(v)
    if isinstance(v, (int, float)):
        return int(v)
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return None
        try:
            return int(s)
        except ValueError:
            try:
                return int(float(s))
            except ValueError:
                return None
    return None


def _parse_per_user_cap(detail: dict) -> Optional[float]:
    """Per-user max subscription in the underlying asset. Binance field names vary
    across product types; try several common ones.
    """
    for key in ("userPurchaseCap", "userTotalAmountLimit", "personalQuota", "maxPurchaseAmountPerUser"):
        v = detail.get(key)
        if v not in (None, "", "0", "0.00"):
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return None


def _extract_tiers(detail: dict, has_tier_apy: bool) -> list[dict]:
    """Return the raw tier ladder for provenance. Shape TBD across product types;
    preserve verbatim so downstream cohorting can inspect later.
    """
    if not has_tier_apy:
        return []
    for key in ("tierApyList", "apyTiers", "rateLevelList"):
        v = detail.get(key)
        if isinstance(v, list) and v:
            return [t for t in v if isinstance(t, dict)]
    return []
