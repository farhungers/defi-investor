"""Bitget spot L2 order-book WebSocket client (Phase 3e prototype).

Endpoint (public, no auth): wss://ws.bitget.com/v2/ws/public
Subscription payload:
    {"op": "subscribe", "args": [{"instType": "SPOT", "channel": "books5", "instId": "BTCUSDT"}]}

Bitget offers three depth channels:
    books      full L2 depth, initial snapshot + delta pushes
    books5     top-5 levels, snapshot push every 100ms
    books15    top-15 levels

For HYPOTHESIS_A3's depth_asymmetry_5min feature (top-5 each side over
5-minute windows), `books5` is the correct product — enough resolution for
the feature, cheap bandwidth, no delta-reconstruction bugs.

This module is a PROTOTYPE. It connects, subscribes, prints payloads to
stdout, and exits on Ctrl-C. Storage (Supabase / disk) and feature
computation live in sibling modules.

Deploy model note: this needs a persistent runner (GH Actions is
inappropriate — 5min timeout, cron re-runs would reopen connections). See
docs/ORDERBOOK_DESIGN.md for options.
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


LOG = logging.getLogger("defi_investor.orderbook.bitget_l2")
VENUE = "bitget"

BITGET_PUBLIC_WS = "wss://ws.bitget.com/v2/ws/public"

# Bitget requires a ping every 30s to keep the connection alive; otherwise
# the server closes with code 1006. Reference: Bitget WS v2 docs.
PING_INTERVAL_S = 25.0

# Reconnect backoff: exponential from 1s to 60s cap.
RECONNECT_MIN_S = 1.0
RECONNECT_MAX_S = 60.0


def _parse_books5_payload(msg: dict) -> Iterable[L2Snapshot]:
    """Yield L2Snapshot objects for a books5-channel push.

    Bitget push shape:
        {"action":"snapshot","arg":{"instType":"SPOT","channel":"books5","instId":"BTCUSDT"},
         "data":[{"asks":[["price","size"],...],"bids":[...],"ts":"1785238523000"}]}
    """
    arg = msg.get("arg", {})
    inst_id = arg.get("instId")
    if not inst_id or arg.get("channel") != "books5":
        return
    received_at = datetime.now(timezone.utc).isoformat()
    for row in msg.get("data", []) or []:
        try:
            ts = int(row.get("ts", 0))
            bids = [(float(p), float(s)) for p, s in (row.get("bids") or [])[:5]]
            asks = [(float(p), float(s)) for p, s in (row.get("asks") or [])[:5]]
        except (TypeError, ValueError) as e:
            LOG.warning("books5 row parse failed for %s: %s", inst_id, e)
            continue
        yield L2Snapshot(
            venue=VENUE,
            inst_id=inst_id,
            received_at=received_at,
            exchange_ts_ms=ts,
            bids=bids,
            asks=asks,
        )


async def _subscribe(ws: WebSocketClientProtocol, inst_ids: list[str]) -> None:
    args = [
        {"instType": "SPOT", "channel": "books5", "instId": inst}
        for inst in inst_ids
    ]
    payload = {"op": "subscribe", "args": args}
    await ws.send(json.dumps(payload))
    LOG.info("subscribed to books5 for %d symbols: %s", len(inst_ids), inst_ids)


async def _pinger(ws: WebSocketClientProtocol, stop: asyncio.Event) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=PING_INTERVAL_S)
        except asyncio.TimeoutError:
            try:
                # Bitget accepts a raw text "ping" or a JSON {"op":"ping"}.
                await ws.send("ping")
            except Exception as e:  # noqa: BLE001
                LOG.warning("ping failed: %s", e)
                return


async def _consume(
    ws: WebSocketClientProtocol,
    on_snapshot,
    stop: asyncio.Event,
) -> None:
    """Read messages until connection drops or stop is set."""
    async for raw in ws:
        if stop.is_set():
            return
        if raw == "pong":
            continue
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            LOG.warning("non-JSON frame: %r", raw[:80])
            continue
        if msg.get("event") == "subscribe":
            LOG.info("subscribe ack: %s", msg.get("arg"))
            continue
        if msg.get("event") == "error":
            LOG.error("server error: %s", msg)
            continue
        for snap in _parse_books5_payload(msg):
            on_snapshot(snap)


async def run_client(inst_ids: list[str], on_snapshot, stop: asyncio.Event) -> None:
    """Connect, subscribe, consume. Reconnect with exponential backoff on drop."""
    backoff = RECONNECT_MIN_S
    while not stop.is_set():
        try:
            async with websockets.connect(BITGET_PUBLIC_WS, open_timeout=10) as ws:
                LOG.info("connected to %s", BITGET_PUBLIC_WS)
                await _subscribe(ws, inst_ids)
                backoff = RECONNECT_MIN_S  # reset on successful connect
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
            # Windows: signal_handler on asyncio isn't supported; Ctrl-C
            # still raises KeyboardInterrupt in the main task.
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
        help="Bitget spot inst IDs to subscribe (default: BTCUSDT ETHUSDT)",
    )
    args = parser.parse_args()
    try:
        asyncio.run(_main_async(args.symbols))
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
