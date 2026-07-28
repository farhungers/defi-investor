"""HTTP fetch layer for Binance Simple Earn.

Isolated from the parser so the parser stays deterministic (JSON in → events
out) and the caller can mock the fetch in tests.

Endpoint discovered 2026-07-28 via probe:
  GET https://www.binance.com/bapi/earn/v1/friendly/finance-earn/simple-earn/homepage/details
      ?pageIndex=<1-based>&pageSize=<<=50>

The `data.total` field carries the population count; the caller paginates
until >= total or a short guard iteration cap is hit.
"""
from __future__ import annotations

import logging
import time
from typing import Optional

import httpx

from .models import SCRAPER_VERSION


LOG = logging.getLogger("defi_investor.binance_earn_fetch")

BASE_URL = "https://www.binance.com/bapi/earn/v1/friendly/finance-earn/simple-earn/homepage/details"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)
RESEARCH_UA = f"defi-investor-research/{SCRAPER_VERSION} (research; contact via GitHub)"

# Conservative page size — Binance accepts up to 50 in practice. Larger sizes
# were not tested. Small enough to stay well under any per-request response
# size limit, large enough that ~421 products fetch in ~9 requests.
PAGE_SIZE = 50

# Hard cap on pages we'll follow before bailing. 421 total / 50 per page = 9
# pages; 20 gives room for growth without runaway.
MAX_PAGES = 20

# Politeness delay between paginated requests. Bitget doesn't require it but
# Binance is stricter with rate-limit responses on bapi.
INTER_PAGE_SLEEP_S = 0.3


class FetchError(Exception):
    pass


def fetch_simple_earn_all(
    *,
    client: Optional[httpx.Client] = None,
    timeout: float = 30.0,
    ua: str = BROWSER_UA,
) -> list[dict]:
    """Fetch every Simple Earn product across all pages.

    Returns the flattened list of raw product dicts (no envelope). The caller
    passes this to parsers/binance_earn.parse_homepage_response() indirectly
    by wrapping in an envelope, OR calls the parser page-by-page — the
    dry-run CLI does the latter for clarity.
    """
    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={
                "User-Agent": ua,
                "Accept": "application/json",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
            follow_redirects=True,
        )
    try:
        products: list[dict] = []
        for page_index in range(1, MAX_PAGES + 1):
            envelope = _fetch_page(client, page_index=page_index, page_size=PAGE_SIZE)
            page_list = envelope.get("data", {}).get("list", [])
            total_str = envelope.get("data", {}).get("total")
            try:
                total = int(total_str) if total_str is not None else None
            except (TypeError, ValueError):
                total = None

            if not isinstance(page_list, list):
                LOG.warning("page %d: 'list' not a list, breaking", page_index)
                break

            LOG.info(
                "binance page=%d got=%d cumulative=%d total_advertised=%s",
                page_index, len(page_list), len(products) + len(page_list), total,
            )

            products.extend(page_list)

            if total is not None and len(products) >= total:
                break
            if not page_list:
                break
            if page_index < MAX_PAGES:
                time.sleep(INTER_PAGE_SLEEP_S)

        return products
    finally:
        if close_after:
            client.close()


def _fetch_page(client: httpx.Client, *, page_index: int, page_size: int) -> dict:
    """One page fetch. Raises FetchError on any non-recoverable issue."""
    params = {"pageIndex": page_index, "pageSize": page_size}
    try:
        r = client.get(BASE_URL, params=params)
    except httpx.HTTPError as e:
        raise FetchError(f"binance page {page_index}: network error: {e}") from e

    if r.status_code != 200:
        raise FetchError(
            f"binance page {page_index}: HTTP {r.status_code} body={r.text[:200]}"
        )

    try:
        envelope = r.json()
    except ValueError as e:
        raise FetchError(f"binance page {page_index}: JSON decode failed: {e}") from e

    if not isinstance(envelope, dict):
        raise FetchError(f"binance page {page_index}: envelope not dict")
    if envelope.get("code") != "000000":
        raise FetchError(
            f"binance page {page_index}: API error code={envelope.get('code')!r} "
            f"message={envelope.get('message')!r}"
        )

    return envelope
