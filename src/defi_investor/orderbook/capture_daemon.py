"""L2 capture daemon — the persistent runnable for Phase 3e.

Ties together:
- universe.build_universe(sb)          → list of inst_ids per venue
- bitget_l2.run_client / binance_l2.run_client → WS subscribers
- storage.BatchedL2Writer(sb)          → async batched Supabase upserts

Run:
    python -m defi_investor.orderbook.capture_daemon
    python -m defi_investor.orderbook.capture_daemon --venues bitget
    python -m defi_investor.orderbook.capture_daemon --max-symbols 50 --dry-run

Env:
    SUPABASE_URL
    SUPABASE_SERVICE_ROLE_KEY

Notes on the current scope:
- Universe is queried at startup only. Hot-reload on universe change is
  deferred; restart the daemon after new Earn products list. In practice
  daily restart is enough for A3's forward-looking data.
- --dry-run skips DB storage; WS clients run and emit periodic stats
  via the writer's counters. Useful to check connectivity.
- Deploy target is user's decision — see docs/ORDERBOOK_DESIGN.md.
- Bitget subscription payload limits: docs cap ~50 subscriptions per
  message. If universe > 50 for Bitget, the client splits into batches
  automatically (subscribe several times in one connection). Binance
  combined-stream URL has a practical URL-length ceiling of ~200 streams;
  we split similarly.
"""
from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import sys
import time
from typing import Optional

from dotenv import load_dotenv

from .storage import BatchedL2Writer
from .universe import UniverseEntry, build_universe


LOG = logging.getLogger("defi_investor.orderbook.capture_daemon")

# Per-venue subscription batch sizes (below API-doc limits, with margin).
BITGET_MAX_SUBS_PER_MSG = 40
BINANCE_MAX_STREAMS_PER_URL = 150

# Emit combined pipeline stats at this cadence
STATS_INTERVAL_S = 60.0


def _make_supabase_client() -> Optional[object]:
    url = os.environ.get("SUPABASE_URL")
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        return None
    from supabase import create_client
    return create_client(url, key)


def _chunks(seq: list, n: int):
    for i in range(0, len(seq), n):
        yield seq[i:i + n]


async def _run_bitget_batches(
    inst_ids: list[str],
    on_snapshot,
    stop: asyncio.Event,
) -> None:
    """Spawn one bitget_l2.run_client per subscription batch, run concurrently."""
    from .bitget_l2 import run_client
    tasks = [
        asyncio.create_task(
            run_client(list(batch), on_snapshot, stop),
            name=f"bitget_ws_batch_{i}",
        )
        for i, batch in enumerate(_chunks(inst_ids, BITGET_MAX_SUBS_PER_MSG))
    ]
    if not tasks:
        return
    await asyncio.gather(*tasks, return_exceptions=True)


async def _run_binance_batches(
    inst_ids: list[str],
    on_snapshot,
    stop: asyncio.Event,
) -> None:
    from .binance_l2 import run_client
    tasks = [
        asyncio.create_task(
            run_client(list(batch), on_snapshot, stop),
            name=f"binance_ws_batch_{i}",
        )
        for i, batch in enumerate(_chunks(inst_ids, BINANCE_MAX_STREAMS_PER_URL))
    ]
    if not tasks:
        return
    await asyncio.gather(*tasks, return_exceptions=True)


async def _stats_loop(writer: BatchedL2Writer, stop: asyncio.Event) -> None:
    """Periodic combined stats log line."""
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=STATS_INTERVAL_S)
        except asyncio.TimeoutError:
            LOG.info("daemon stats: %s", writer.stats())


async def _run(
    venues: list[str],
    max_symbols: Optional[int],
    dry_run: bool,
) -> int:
    sb = _make_supabase_client()
    if sb is None and not dry_run:
        LOG.error("SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY missing (use --dry-run to skip DB)")
        return 2

    # Universe from Supabase (or a hardcoded prototype list in dry-run w/o creds)
    if sb is not None:
        universe: list[UniverseEntry] = build_universe(sb)
    else:
        LOG.warning("no supabase; falling back to prototype universe [BTC, ETH]")
        universe = [
            UniverseEntry("BTC", "BTCUSDT", "BTCUSDT", "manual"),
            UniverseEntry("ETH", "ETHUSDT", "ETHUSDT", "manual"),
        ]

    if max_symbols is not None and len(universe) > max_symbols:
        LOG.info("capping universe from %d to %d symbols", len(universe), max_symbols)
        universe = universe[:max_symbols]

    bitget_ids = (
        [e.bitget_inst_id for e in universe if e.bitget_inst_id]
        if "bitget" in venues else []
    )
    binance_ids = (
        [e.binance_inst_id for e in universe if e.binance_inst_id]
        if "binance" in venues else []
    )

    LOG.info(
        "daemon start: %d bitget, %d binance, dry_run=%s",
        len(bitget_ids), len(binance_ids), dry_run,
    )
    if not bitget_ids and not binance_ids:
        LOG.error("no symbols to subscribe; exiting")
        return 1

    writer = BatchedL2Writer(None if dry_run else sb)
    await writer.start()

    stop = asyncio.Event()

    def _on_snap(snap):
        writer.enqueue(snap)

    # Signal handlers where supported (POSIX). Windows falls through to
    # KeyboardInterrupt in the main task.
    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        LOG.info("shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    tasks = []
    if bitget_ids:
        tasks.append(asyncio.create_task(_run_bitget_batches(bitget_ids, _on_snap, stop)))
    if binance_ids:
        tasks.append(asyncio.create_task(_run_binance_batches(binance_ids, _on_snap, stop)))
    stats_task = asyncio.create_task(_stats_loop(writer, stop))
    tasks.append(stats_task)

    try:
        await asyncio.gather(*tasks, return_exceptions=True)
    except KeyboardInterrupt:
        stop.set()
    finally:
        stop.set()
        await writer.stop()
        LOG.info("daemon exit: %s", writer.stats())
    return 0


def main() -> int:
    load_dotenv()
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--venues", default="bitget,binance",
        help="comma-separated: bitget,binance",
    )
    parser.add_argument(
        "--max-symbols", type=int, default=None,
        help="cap universe size (default: no cap)",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="skip Supabase writes; log stats only",
    )
    args = parser.parse_args()

    venues = [v.strip().lower() for v in args.venues.split(",") if v.strip()]
    for v in venues:
        if v not in ("bitget", "binance"):
            parser.error(f"unknown venue: {v}")

    try:
        return asyncio.run(_run(venues, args.max_symbols, args.dry_run))
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    sys.exit(main())
