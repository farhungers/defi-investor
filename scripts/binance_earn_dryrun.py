"""Dry-run fetch + parse of Binance Simple Earn products. No DB writes.

Prints a summary and optionally dumps events to JSONL for inspection.

Usage:
    python scripts/binance_earn_dryrun.py
    python scripts/binance_earn_dryrun.py --dump data/raw/binance_dryrun.jsonl
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from defi_investor.binance_earn_fetch import fetch_simple_earn_all
from defi_investor.parsers.binance_earn import parse_homepage_response


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")

    parser = argparse.ArgumentParser()
    parser.add_argument("--dump", type=Path, default=None, help="write parsed events to this JSONL path")
    args = parser.parse_args()

    raw_products = fetch_simple_earn_all()
    print("-" * 72)
    print(f"Fetched {len(raw_products)} raw products from Binance Simple Earn")
    if not raw_products:
        print("No products returned — API shape may have changed. Aborting.")
        return 1

    envelope_shim = {"code": "000000", "data": {"list": raw_products, "total": str(len(raw_products))}}
    events = parse_homepage_response(envelope_shim)
    print(f"Parsed  {len(events)} EarnEvents (venue=binance)")

    print()
    print("APY distribution (percentage-points):")
    apys = [e.max_apy for e in events if e.max_apy is not None]
    if apys:
        apys_sorted = sorted(apys)
        print(f"  n={len(apys)}  min={apys_sorted[0]:.2f}  max={apys_sorted[-1]:.2f}")
        print(f"  p50={apys_sorted[len(apys_sorted)//2]:.2f}  p90={apys_sorted[int(len(apys_sorted)*0.9)]:.2f}")
        print(f"  >= 20% (MIN_APR_FOR_ALERT default): {sum(1 for a in apys if a >= 20.0)}")
        print(f"  >= 50%: {sum(1 for a in apys if a >= 50.0)}")
    else:
        print("  (no APY values parsed — investigate)")

    print()
    print("Product-type distribution (second_biz_line):")
    for bl, n in Counter(e.second_biz_line for e in events).most_common():
        print(f"  {bl:20s} {n}")

    print()
    print("Sold-out flag distribution:")
    print(f"  sold_out=True:  {sum(1 for e in events if e.sold_out)}")
    print(f"  sold_out=False: {sum(1 for e in events if not e.sold_out)}")

    print()
    print("Data quality:")
    for dq, n in Counter(e.data_quality for e in events).most_common():
        print(f"  {dq:20s} {n}")

    print()
    print("Top 10 by APY:")
    for e in sorted(events, key=lambda x: -(x.max_apy or 0))[:10]:
        cap = f"cap={e.per_user_cap_underlying}" if e.per_user_cap_underlying else "cap=None"
        lock = f"{e.period_days}d" if e.period_days else "flex"
        so = " SOLD_OUT" if e.sold_out else ""
        print(f"  {e.coin_name:8s}  {(e.max_apy or 0):6.2f}%  {lock:5s}  {e.second_biz_line:18s}  {cap}{so}")

    if args.dump is not None:
        args.dump.parent.mkdir(parents=True, exist_ok=True)
        ts = datetime.now(timezone.utc).isoformat()
        with args.dump.open("w", encoding="utf-8") as f:
            for e in events:
                d = e.to_dict()
                d["_dryrun_scraped_at"] = ts
                f.write(json.dumps(d, default=str) + "\n")
        print()
        print(f"Wrote {len(events)} rows to {args.dump}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
