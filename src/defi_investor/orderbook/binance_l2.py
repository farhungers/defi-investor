"""Binance spot L2 order-book WebSocket client (Phase 3e).

Endpoint (public, no auth): wss://stream.binance.com:9443/stream
Stream name for top-5 partial depth at 100ms cadence:
    <symbol lowercase>@depth5@100ms

Combined-stream envelope:
    {"stream":"btcusdt@depth5@100ms",
     "data":{"lastUpdateId":..., "bids":[["p","s"],...], "asks":[["p","s"],...]}}

Binance partial-depth streams do NOT include an exchange timestamp inside
the data payload. We use the wall-clock receive time as `exchange_ts_ms`
here for consistency with L2Snapshot's shape; the true server-side event
time is unavailable on this stream. If sub-100ms clock skew becomes a
gate-relevant confound, switch to the individual-symbol diff-depth stream
(<symbol>@depth@100ms) which carries E (event time), rebuild top-5 in
process, and pay the reconstruction complexity.

Same runtime shape as bitget_l2:
    async def run_client(inst_ids, on_snapshot, stop) -> None:
Deploy model note: identical to Bitget — see docs/ORDERBOOK_DESIGN.md.
"""
from __future__ import annotations

import asyncio
import json
import logging
import signal
from datetime import datetime, timezone
from typing import Iterable, Optional

import websockets
from websockets.asyncio.client import ClientConnection as WebSocketClientProtocol

from . import L2Snapshot


LOG = logging.getLogger("defi_investor.orderbook.binance_l2")
VENUE = "binance"

BINANCE_PUBLIC_WS = "wss://stream.binance.com:9443/stream"

# Binance recommends a pong at least every 3 minutes; server pings every 3 min.
# We proactively send a ping every 60s to detect zombie connections faster.
PING_INTERVAL_S = 60.0

RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 60.0


def _stream_name(inst_id: str) -> str:
    """BTCUSDT -> btcusdt@depth5@100ms"""
    return f"{inst_id.lower()}@depth5@100ms"


def _parse_depth5_payload(msg: dict) -> Iterable[L2Snapshot]:
    """Yield L2Snapshot for a Binance combined-stream depth5 push."""
    stream = msg.get("stream", "")
    if "@depth5" not in stream:
        return
    # stream is like 'btcusdt@depth5@100ms'; symbol is the part before '@'
    sym = stream.split("@", 1)[0].upper()
    data = msg.get("data") or {}
    raw_bids = data.get("bids") or []
    raw_asks = data.get("asks") or []
    try:
        bids = [(float(p), float(s)) for p, s in raw_bids[:5]]
        asks = [(float(p), float(s)) for p, s in raw_asks[:5]]
    except (TypeError, ValueError) as e:
        LOG.warning("depth5 parse failed for %s: %s", sym, e)
        return

    now = datetime.now(timezone.utc)
    yield L2Snapshot(
        venue=VENUE,
        inst_id=sym,
        received_at=now.isoformat(),
        exchange_ts_ms=int(now.timestamp() * 1000),
        bids=bids,
        asks=asks,
    )


async def _pinger(ws: WebSocketClientProtocol, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=PING_INTERVAL_S)
        except asyncio.TimeoutError:
            try:
                await ws.ping()
            except Exception as e:  # noqa: BLE001
                LOG.warning("ping failed: %s", e)
                return


async def _consume(
    ws: WebSocketClientProtocol,
    on_snapshot,
    stop: asyncio.Event,
) -> None:
    async for raw in ws:
        if stop.is_set():
            return
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            LOG.warning("non-JSON frame: %r", raw[:80])
            continue
        # Binance combined-stream envelope has 'stream' and 'data'
        if "stream" in msg and "data" in msg:
            for snap in _parse_depth5_payload(msg):
                on_snapshot(snap)
            continue
        # Ignore subscription acks (result: null, id: ...) and errors
        if "result" in msg:
            LOG.info("binance ack: %s", msg)
            continue
        if msg.get("error"):
            LOG.error("server error: %s", msg)


async def run_client(inst_ids: list[str], on_snapshot, stop: asyncio.Event) -> None:
    """Connect, subscribe, consume. Auto-reconnect with exponential backoff."""
    streams = "/".join(_stream_name(i) for i in inst_ids)
    url = f"{BINANCE_PUBLIC_WS}?streams={streams}"
    backoff = RECONNECT_MIN_S
    while not stop.is_set():
        try:
            async with websockets.connect(url, open_timeout=10) as ws:
                LOG.info("connected to %s (%d streams)", BINANCE_PUBLIC_WS, len(inst_ids))
                backoff = RECONNECT_MIN_S
                ping_task = asyncio.create_task(_pinger(ws, stop))
                try:
                    await _consume(ws, on_snapshot, stop)
                finally:
                    ping_task.cancel()
        except Exception as e:  # noqa: BLE001
            if stop.is_set():
                return
            LOG.warning("ws loop error: %s -- reconnecting in %.1fs", e, backoff)
            try:
                await asyncio.wait_for(stop.wait(), timeout=backoff)
            except asyncio.TimeoutError:
                pass
            backoff = min(backoff * 2, RECONNECT_MAX_S)


async def _main_async(inst_ids: list[str]) -> None:
    stop = asyncio.Event()

    def _print(snap: L2Snapshot) -> None:
        best_bid = snap.bids[0] if snap.bids else (None, None)
        best_ask = snap.asks[0] if snap.asks else (None, None)
        print(
            f"{snap.received_at}  {snap.inst_id:12s}  "
            f"bid={best_bid[0]}({best_bid[1]})  ask={best_ask[0]}({best_ask[1]})",
            flush=True,
        )

    loop = asyncio.get_running_loop()

    def _shutdown() -> None:
        LOG.info("shutdown signal received")
        stop.set()

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _shutdown)
        except NotImplementedError:
            pass

    try:
        await run_client(inst_ids, _print, stop)
    except KeyboardInterrupt:
        stop.set()


def main() -> int:
    import argparse
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "symbols", nargs="*", default=["BTCUSDT", "ETHUSDT"],
        help="Binance spot symbols to subscribe (default: BTCUSDT ETHUSDT)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_main_async(args.symbols))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
