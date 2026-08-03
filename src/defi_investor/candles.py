"""Bitget public candle fetcher for the Phase 2 labeler.

Endpoint (verified 2026-07-10):

    GET https://api.bitget.com/api/v2/mix/market/candles
    Params:
        symbol         e.g. LABUSDT
        productType    USDT-FUTURES for USDT-margined perp
        granularity    1m 5m 15m 30m 1H 4H 6H 12H 1D 3D 1W 1M
        startTime      epoch ms (optional)
        endTime        epoch ms (optional)
        limit          default 100, max 1000

Response shape:

    {"code":"00000","msg":"success","requestTime":...,
     "data":[[ts_ms_str, o, h, l, c, base_vol, quote_vol, ...], ...]}

Perp returns 7 columns. Spot returns 8 columns (adds usdt_vol as an 8th
field, which for USDT-quoted pairs is identical to quote_vol). Any
trailing columns are dropped by `_to_frame`.

All numeric fields are STRINGS on the wire. `data` is sorted oldest-first.

The fetcher tries USDT-M perp first, falls back to spot (different endpoint,
similar shape). If neither exists for the coin, returns (None, provenance).
Labeler treats that as "event unlabelable — tag and exclude from primary
per METHOD §5.1".

No disk cache in Phase 2 v1. GH Actions runners are ephemeral; per-run
re-fetch is cheap (~48 4H candles per event). Add a Supabase-backed cache
if per-run cost becomes a bottleneck.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

import httpx
import pandas as pd


LOG = logging.getLogger("defi_investor.candles")

PERP_URL = "https://api.bitget.com/api/v2/mix/market/candles"
SPOT_URL = "https://api.bitget.com/api/v2/spot/market/candles"
USER_AGENT = "defi-investor-research/0.2.0 (Bitget Earn hypothesis test)"

# Bitget accepts up to 1000; use 200 to stay well below any silent throttle
_PAGE_LIMIT = 200


@dataclass(frozen=True)
class CandleFetch:
    """Provenance record for one fetch call."""
    url: str
    market: str            # 'perp' | 'spot' | 'none'
    symbol: str
    granularity: str
    start_ms: int
    end_ms: int
    n_bars: int
    fetched_at: str        # ISO 8601 UTC
    http_status: int
    error: Optional[str] = None
    pages: int = 1


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _to_frame(rows: list) -> pd.DataFrame:
    """Convert Bitget's list-of-lists into a numeric OHLCV DataFrame."""
    if not rows:
        return pd.DataFrame(columns=["open", "high", "low", "close", "base_vol", "quote_vol"])
    # Spot returns 8 cols (adds usdt_vol), perp returns 7. Drop any trailing
    # columns beyond the 7 we consume so both endpoints share one shape.
    trimmed = [row[:7] for row in rows]
    df = pd.DataFrame(trimmed, columns=[
        "ts_ms", "open", "high", "low", "close", "base_vol", "quote_vol",
    ])
    df["ts"] = pd.to_datetime(df["ts_ms"].astype("int64"), unit="ms", utc=True)
    for col in ("open", "high", "low", "close", "base_vol", "quote_vol"):
        df[col] = pd.to_numeric(df[col], errors="coerce")
    df = df.drop(columns=["ts_ms"]).set_index("ts").sort_index()
    return df


def _fetch_page(
    url: str, *, symbol: str, granularity: str,
    start_ms: int, end_ms: int, product_type: Optional[str],
    client: httpx.Client,
) -> tuple[Optional[list], int, Optional[str]]:
    """Fetch one page. Returns (rows_or_None, http_status, error_or_None)."""
    params: dict = {
        "symbol": symbol,
        "granularity": granularity,
        "startTime": str(start_ms),
        "endTime": str(end_ms),
        "limit": str(_PAGE_LIMIT),
    }
    if product_type:
        params["productType"] = product_type
    try:
        r = client.get(url, params=params, timeout=20.0)
    except httpx.HTTPError as e:
        return None, 0, f"http_error: {e}"
    if r.status_code != 200:
        return None, r.status_code, f"non_200: {r.text[:200]}"
    try:
        body = r.json()
    except ValueError:
        return None, r.status_code, "invalid_json"
    if body.get("code") != "00000":
        return None, r.status_code, f"api_code={body.get('code')} msg={body.get('msg')}"
    return body.get("data") or [], r.status_code, None


# Granularity -> milliseconds. Used by the backward-fill tolerance in
# _fetch_market. '1M' (monthly) is approximated at 30 days.
_GRANULARITY_MS: dict[str, int] = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "30m": 1_800_000,
    "1H": 3_600_000,
    "4H": 14_400_000,
    "6H": 21_600_000,
    "12H": 43_200_000,
    "1D": 86_400_000,
    "3D": 259_200_000,
    "1W": 604_800_000,
    "1M": 30 * 86_400_000,
}


def _granularity_to_ms(g: str) -> int:
    return _GRANULARITY_MS.get(g, 60_000)


# Hard cap on API round-trips per fetch to prevent runaway loops on weird
# responses. A 168h (7d) 1m walk = ~51 pages; retention-limited walks bail
# earlier via empty-response break. 250 gives room for both.
_MAX_PAGES = 250


def _fetch_market(
    url: str, *, symbol: str, granularity: str,
    start_ms: int, end_ms: int, product_type: Optional[str],
    client: httpx.Client,
) -> tuple[Optional[pd.DataFrame], int, Optional[str], int]:
    """Fetch across paginated windows. Returns (df, last_status, error, n_pages).

    Two-phase strategy to cover Bitget's inconsistent paging behavior:

    Phase 1 (forward walk): request [start_ms, end_ms], advance start past
    the last returned ts. Works for oldest-first endpoints (4H perp etc.).

    Phase 2 (backward fill): if Phase 1's earliest returned bar is far past
    the requested start_ms (Bitget's 1m mix-candles endpoint empirically
    returns the newest ~200 bars within a wide window, ignoring startTime),
    walk backward by shrinking cursor_end to first_ts - 1 each iteration
    until start_ms is reached or an empty response ends coverage.

    Regression context: without Phase 2, all 27 sold-out events in the
    2026-07-29 v0.3.0 A2b backfill labelled as anchor_before_first_walk_bar
    because the fetcher's forward-walk assumption skipped past the anchor.
    """
    granularity_ms = _granularity_to_ms(granularity)
    tolerance_ms = granularity_ms * 2  # allow two-bar slop for API rounding
    all_rows_by_ts: dict[int, list] = {}
    n_pages = 0
    last_status = 0

    # Phase 1: forward walk from start_ms.
    cursor = start_ms
    while cursor < end_ms and n_pages < _MAX_PAGES:
        rows, status, err = _fetch_page(
            url, symbol=symbol, granularity=granularity,
            start_ms=cursor, end_ms=end_ms,
            product_type=product_type, client=client,
        )
        n_pages += 1
        last_status = status
        if err is not None:
            return None, status, err, n_pages
        if not rows:
            break
        for row in rows:
            all_rows_by_ts.setdefault(int(row[0]), row)
        last_ts_ms = max(int(r[0]) for r in rows)
        if last_ts_ms + 1 <= cursor:
            break  # defensive: no forward progress
        cursor = last_ts_ms + 1
        if len(rows) < _PAGE_LIMIT:
            break  # last page

    # Phase 2: backward fill if the earliest bar is past start_ms + tolerance.
    if all_rows_by_ts:
        min_ts = min(all_rows_by_ts)
        if min_ts > start_ms + tolerance_ms:
            cursor_end = min_ts - 1
            while cursor_end > start_ms and n_pages < _MAX_PAGES:
                rows, status, err = _fetch_page(
                    url, symbol=symbol, granularity=granularity,
                    start_ms=start_ms, end_ms=cursor_end,
                    product_type=product_type, client=client,
                )
                n_pages += 1
                last_status = status
                if err is not None:
                    return None, status, err, n_pages
                if not rows:
                    break
                added = False
                for row in rows:
                    ts = int(row[0])
                    if ts not in all_rows_by_ts:
                        all_rows_by_ts[ts] = row
                        added = True
                first_ts_this_page = min(int(r[0]) for r in rows)
                if first_ts_this_page <= start_ms + tolerance_ms:
                    break
                new_cursor_end = first_ts_this_page - 1
                if new_cursor_end >= cursor_end or not added:
                    break  # defensive: no backward progress
                cursor_end = new_cursor_end

    all_rows = [all_rows_by_ts[ts] for ts in sorted(all_rows_by_ts)]
    df = _to_frame(all_rows)
    # Trim to the requested window (Bitget can overshoot by one bar)
    if not df.empty:
        df = df[(df.index >= pd.to_datetime(start_ms, unit="ms", utc=True))
                & (df.index <= pd.to_datetime(end_ms, unit="ms", utc=True))]
    return df, last_status, None, n_pages


# Bitget spot uses different granularity strings than perp. Discovered
# empirically 2026-07-28 via scripts/probe_bitget_candle_retention.py:
#   perp:  1m 5m 15m 30m 1H 4H 6H 12H 1D 3D 1W 1M
#   spot:  1min 5min 15min 30min 1h 4h 6h 12h 1day 1week 1M (+ *utc variants)
# Without this translation, spot fallback has been silently rejecting
# every fetch since the labeler was written — no spot-only coins were
# ever labeled.
_PERP_TO_SPOT_GRANULARITY = {
    "1m": "1min",
    "5m": "5min",
    "15m": "15min",
    "30m": "30min",
    "1H": "1h",
    "4H": "4h",
    "6H": "6h",
    "12H": "12h",
    "1D": "1day",
    "3D": "3Dutc",   # no non-utc equivalent on spot
    "1W": "1week",
    "1M": "1M",
}


def _spot_granularity(g: str) -> str:
    """Translate a perp-format granularity to the spot-endpoint format."""
    return _PERP_TO_SPOT_GRANULARITY.get(g, g)


def fetch_candles(
    *,
    symbol: str,
    start_ms: int,
    end_ms: int,
    granularity: str = "4H",
    client: Optional[httpx.Client] = None,
) -> tuple[Optional[pd.DataFrame], CandleFetch]:
    """Fetch OHLCV from Bitget. Perp first, spot fallback.

    Args:
        symbol: e.g. 'LABUSDT'. Must match Bitget's naming.
        start_ms, end_ms: inclusive epoch-ms window.
        granularity: '1m'|'5m'|'15m'|'30m'|'1H'|'4H'|'6H'|'12H'|'1D'|'3D'|'1W'|'1M'.
        client: optional httpx.Client to reuse across many events.

    Returns:
        (df, provenance). df is None if neither perp nor spot returned data.
    """
    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        )
    try:
        # Try perp
        df, status, err, pages = _fetch_market(
            PERP_URL, symbol=symbol, granularity=granularity,
            start_ms=start_ms, end_ms=end_ms,
            product_type="USDT-FUTURES", client=client,
        )
        if df is not None and not df.empty:
            return df, CandleFetch(
                url=PERP_URL, market="perp", symbol=symbol,
                granularity=granularity, start_ms=start_ms, end_ms=end_ms,
                n_bars=len(df), fetched_at=_now_iso(),
                http_status=status, error=err, pages=pages,
            )
        LOG.info("perp empty/failed for %s (err=%s); falling back to spot",
                 symbol, err)
        # Fall back to spot. Spot uses a different granularity string
        # format — see _PERP_TO_SPOT_GRANULARITY.
        spot_g = _spot_granularity(granularity)
        df2, status2, err2, pages2 = _fetch_market(
            SPOT_URL, symbol=symbol, granularity=spot_g,
            start_ms=start_ms, end_ms=end_ms,
            product_type=None, client=client,
        )
        if df2 is not None and not df2.empty:
            return df2, CandleFetch(
                url=SPOT_URL, market="spot", symbol=symbol,
                granularity=granularity, start_ms=start_ms, end_ms=end_ms,
                n_bars=len(df2), fetched_at=_now_iso(),
                http_status=status2, error=err2, pages=pages2,
            )
        return None, CandleFetch(
            url=SPOT_URL, market="none", symbol=symbol,
            granularity=granularity, start_ms=start_ms, end_ms=end_ms,
            n_bars=0, fetched_at=_now_iso(),
            http_status=status2, error=err2 or err, pages=pages + pages2,
        )
    finally:
        if close_after:
            client.close()


def compute_atr(df: pd.DataFrame, *, period: int = 24) -> pd.Series:
    """Wilder's ATR on an OHLC DataFrame indexed by timestamp.

    ATR(t) = EMA(true_range, period) with Wilder smoothing (α = 1/period).
    True range = max(high - low, |high - prev_close|, |low - prev_close|).

    Returns a Series aligned with df.index. NaN for the first `period - 1`
    bars while the smoother warms up.

    Not annualized. Consumers scale by expected horizon.
    """
    if df.empty or len(df) < 2:
        return pd.Series(dtype="float64", index=df.index, name="atr")
    high = df["high"]
    low = df["low"]
    prev_close = df["close"].shift(1)
    tr = pd.concat([
        (high - low).abs(),
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1.0 / period, adjust=False, min_periods=period).mean()
    atr.name = "atr"
    return atr


def compute_sigma_realized(
    df: pd.DataFrame,
    *,
    period: int = 20,
    price_col: str = "close",
) -> pd.Series:
    """Trailing realized volatility of daily log returns.

    Given an OHLC DataFrame indexed by daily bar timestamp, return a Series
    aligned with df.index where each entry is the sample standard deviation
    of the past `period` daily log returns ending at that timestamp
    (inclusive).

    Definition: sigma(t) = std({r_{t-period+1}, ..., r_t}) with population
    normalisation (ddof=0). NOT annualized; consumers scale by horizon.
    First `period` bars are NaN while the rolling window warms up.

    Used by v0.3.0 triple-barrier labeler per HYPOTHESIS_A2b spec:
    barriers set at ±k × sigma_20d where sigma_20d is this function with
    period=20 on daily bars.

    The caller is responsible for passing daily-resolution bars. On 1H or
    finer bars this function will happily compute a rolling std of hourly
    returns, which is a DIFFERENT quantity. Convert to daily bars first.
    """
    if df.empty or price_col not in df.columns:
        return pd.Series(dtype="float64", index=df.index, name=f"sigma_{period}d")
    close = df[price_col].astype("float64")
    log_ret = (close / close.shift(1)).apply(_safe_log)
    sigma = log_ret.rolling(window=period, min_periods=period).std(ddof=0)
    sigma.name = f"sigma_{period}d"
    return sigma


def _safe_log(x: float) -> float:
    """log(x) but returns NaN for non-positive values instead of raising."""
    import math
    if x is None or not isinstance(x, (int, float)) or x <= 0 or math.isnan(x):
        return float("nan")
    return math.log(x)


def resample_to_daily(df: pd.DataFrame) -> pd.DataFrame:
    """Convert a sub-daily OHLCV DataFrame to daily bars (UTC calendar).

    Aggregation: open=first, high=max, low=min, close=last, base_volume=sum,
    quote_volume=sum. Index becomes date-normalized (midnight UTC per day).
    """
    if df.empty:
        return df
    agg = {
        "open": "first",
        "high": "max",
        "low": "min",
        "close": "last",
    }
    for extra in ("base_volume", "quote_volume"):
        if extra in df.columns:
            agg[extra] = "sum"
    daily = df.resample("1D").agg(agg).dropna(how="all")
    return daily
