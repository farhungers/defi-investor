"""Empirical measurement of Bitget candle retention per (endpoint, granularity).

Answers the question raised in docs/OBSERVATIONS.md 2026-07-28: the v0.3.0
backfill saw 4 events fail with `anchor_before_first_walk_bar` (1m candles
didn't extend back to July-9 anchors). Undocumented API-limit or something
else?

Method:
  For each (endpoint, granularity), request 200 candles ending at NOW,
  then step backward in geometric jumps. The oldest bar's timestamp
  each response defines the retention floor for that granularity.

Runs today. Read-only. No Supabase, no writes.
"""
from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import httpx


PERP_URL = "https://api.bitget.com/api/v2/mix/market/candles"
SPOT_URL = "https://api.bitget.com/api/v2/spot/market/candles"
UA = "defi-investor-research/0.3.0 (retention diagnostic)"

# Granularities to test. Bitget accepts: 1m, 5m, 15m, 30m, 1H, 4H, 6H, 12H, 1D
GRANULARITIES = ["1m", "5m", "15m", "1H", "4H", "1D"]

# Test symbol — deep-liquidity spot pair that's been listed for years.
# Any retention floor observed is a floor for retention across the exchange.
SYMBOL = "BTCUSDT"


def _fetch(client, url, symbol, granularity, start_ms, end_ms, is_perp):
    params = {
        "symbol": symbol, "granularity": granularity,
        "startTime": start_ms, "endTime": end_ms, "limit": 200,
    }
    if is_perp:
        params["productType"] = "USDT-FUTURES"
    try:
        r = client.get(url, params=params, timeout=15.0)
        r.raise_for_status()
    except httpx.HTTPError as e:
        return None, f"http_error: {e}"
    body = r.json()
    code = body.get("code")
    if code not in ("00000", "0"):
        return None, f"api_code={code} msg={body.get('msg', '')[:80]}"
    data = body.get("data") or []
    if not data:
        return None, "empty_data"
    # Bitget wire: [[ts_ms_str, o, h, l, c, base_vol, quote_vol], ...]
    ts_values = []
    for row in data:
        if not row:
            continue
        try:
            ts_values.append(int(row[0]))
        except (ValueError, TypeError, IndexError):
            continue
    if not ts_values:
        return None, "no_valid_timestamps"
    return (min(ts_values), max(ts_values), len(ts_values)), None


def find_retention_floor(client, url, granularity, is_perp) -> dict:
    """Binary-ish search for the oldest bar Bitget will return.

    Strategy: fetch at now, then step back doubling. When a fetch returns
    empty or an error, narrow between the last-successful and the failed
    start time to find the actual floor.
    """
    now = datetime.now(timezone.utc)
    now_ms = int(now.timestamp() * 1000)
    window_ms = 200 * _granularity_to_ms(granularity)  # 200 candles wide

    # Try progressively older windows: 1d, 7d, 30d, 90d, 365d, 730d, 1825d ago.
    probes_days_ago = [0, 1, 7, 30, 90, 180, 365, 730, 1825]
    results = []
    for days_ago in probes_days_ago:
        start = now_ms - (days_ago * 86400_000) - window_ms
        end = now_ms - (days_ago * 86400_000)
        got, err = _fetch(client, url, SYMBOL, granularity, start, end, is_perp)
        if err is not None:
            results.append({"days_ago": days_ago, "status": "empty", "err": err})
        else:
            oldest_ms, newest_ms, n = got
            results.append({
                "days_ago": days_ago,
                "status": "ok",
                "n": n,
                "oldest": datetime.fromtimestamp(oldest_ms / 1000, tz=timezone.utc).isoformat(),
                "newest": datetime.fromtimestamp(newest_ms / 1000, tz=timezone.utc).isoformat(),
            })
        time.sleep(0.2)  # be nice to Bitget

    # Deepest successful probe = observed retention floor.
    ok = [r for r in results if r["status"] == "ok"]
    floor = None
    if ok:
        floor = max(r["days_ago"] for r in ok)
    return {"probes": results, "observed_floor_days_ago": floor}


def _granularity_to_ms(g: str) -> int:
    n = int(g[:-1])
    unit = g[-1]
    mult = {"m": 60_000, "H": 3600_000, "D": 86400_000}[unit]
    return n * mult


def main() -> int:
    print(f"Bitget candle retention diagnostic — {datetime.now(timezone.utc).isoformat()}")
    print(f"Symbol: {SYMBOL}")
    print("=" * 80)

    with httpx.Client(headers={"User-Agent": UA, "Accept": "application/json"}) as client:
        for label, url, is_perp in [("PERP", PERP_URL, True), ("SPOT", SPOT_URL, False)]:
            print(f"\n### {label} endpoint")
            print("-" * 60)
            for g in GRANULARITIES:
                result = find_retention_floor(client, url, g, is_perp)
                floor = result["observed_floor_days_ago"]
                if floor is None:
                    print(f"  {g:4s}  no data at ANY probe distance")
                    continue
                oldest_seen = max(
                    (p for p in result["probes"] if p["status"] == "ok"),
                    key=lambda p: p["days_ago"],
                )
                print(f"  {g:4s}  floor >= {floor:5d} days ago  "
                      f"(oldest bar timestamp: {oldest_seen['oldest'][:10]})")
                # Show the first FAIL after the last OK
                first_fail = next(
                    (p for p in result["probes"] if p["status"] == "empty" and p["days_ago"] > floor),
                    None,
                )
                if first_fail:
                    print(f"        first fail beyond floor: {first_fail['days_ago']} days ago "
                          f"({first_fail['err'][:60]})")

    print("\n" + "=" * 80)
    print("Interpretation for v0.3.0 A2b labeler:")
    print("  1m walk needs data back to (anchor - 1 minute) through")
    print("  (anchor + 168h + slack). If 1m floor is < ~180 days, older")
    print("  anchors cannot be labelled retrospectively — noted in")
    print("  docs/OBSERVATIONS.md 2026-07-28.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
