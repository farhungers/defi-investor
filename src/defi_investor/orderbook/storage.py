"""Async batched writer for L2 snapshots.

Sits between the WS clients (bitget_l2, binance_l2) and Supabase. WS
callbacks push into an asyncio.Queue; a background task drains the
queue in batches and inserts to the `orderbook_snapshots_l2` table.

Non-goals in this module:
- Deduplication (we insert on composite PK; conflicts are rare and
  Postgres handles them with upsert semantics).
- Retention (nightly pg_cron per docs/ORDERBOOK_DESIGN.md).
- Feature computation (features.py runs at label-time, not capture-time).

Backpressure model:
- Queue max size = 100k snapshots (~25 MB at typical payload sizes).
- If queue is full when a new snapshot arrives, DROP the OLDEST queued
  snapshot and enqueue the new one. This prefers freshness over
  completeness — the labeler only needs the recent pre-event window.

Batch policy:
- Flush when queue has 500 items OR 2 seconds have elapsed since last
  flush, whichever comes first. Insert as a single upsert (composite PK
  handles rare duplicate exchange_ts within a symbol).

Supabase client is synchronous; we call it via asyncio.to_thread so the
WS event loop stays responsive.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import Optional

from . import L2Snapshot


LOG = logging.getLogger("defi_investor.orderbook.storage")

DEFAULT_QUEUE_MAX = 100_000
DEFAULT_BATCH_SIZE = 500
DEFAULT_MAX_INTERVAL_S = 2.0

# Emit throughput stats to logs at this interval so ops can watch.
STATS_INTERVAL_S = 30.0


class BatchedL2Writer:
    """Async batched writer with drop-oldest backpressure.

    Public interface:
        writer = BatchedL2Writer(sb_client)
        await writer.start()          # spawn drain task
        writer.enqueue(snapshot)      # sync, non-blocking; called from WS callbacks
        await writer.stop()           # drains remaining queue, cancels task
    """

    def __init__(
        self,
        sb_client=None,
        *,
        queue_max: int = DEFAULT_QUEUE_MAX,
        batch_size: int = DEFAULT_BATCH_SIZE,
        max_interval_s: float = DEFAULT_MAX_INTERVAL_S,
    ):
        self._sb = sb_client
        self._queue: deque[L2Snapshot] = deque()
        self._queue_max = queue_max
        self._batch_size = batch_size
        self._max_interval_s = max_interval_s
        self._task: Optional[asyncio.Task] = None
        self._stop_event = asyncio.Event()
        self._condition = asyncio.Event()
        # Counters
        self._n_enqueued = 0
        self._n_dropped = 0
        self._n_flushed = 0
        self._n_flush_batches = 0
        self._n_flush_errors = 0
        self._last_stats_at = time.monotonic()

    # ------------------------- public API -----------------------------

    async def start(self) -> None:
        if self._task is not None:
            raise RuntimeError("writer already started")
        self._task = asyncio.create_task(self._drain_loop(), name="l2_writer_drain")

    def enqueue(self, snap: L2Snapshot) -> None:
        """Non-blocking. Drops oldest if queue full."""
        if len(self._queue) >= self._queue_max:
            self._queue.popleft()
            self._n_dropped += 1
        self._queue.append(snap)
        self._n_enqueued += 1
        # Wake the drain loop if it's blocked waiting
        self._condition.set()

    async def stop(self) -> None:
        """Signal stop, drain remaining, then cancel task."""
        self._stop_event.set()
        self._condition.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=10.0)
            except asyncio.TimeoutError:
                LOG.warning("drain task did not stop within 10s; cancelling")
                self._task.cancel()
                try:
                    await self._task
                except asyncio.CancelledError:
                    pass
            self._task = None

    def stats(self) -> dict:
        return {
            "queue_depth": len(self._queue),
            "enqueued": self._n_enqueued,
            "flushed": self._n_flushed,
            "dropped": self._n_dropped,
            "batches": self._n_flush_batches,
            "flush_errors": self._n_flush_errors,
        }

    # ------------------------- internals ------------------------------

    async def _drain_loop(self) -> None:
        last_flush_at = time.monotonic()
        while not self._stop_event.is_set():
            # Wait until batch is worth flushing OR timeout elapses.
            elapsed = time.monotonic() - last_flush_at
            time_to_wait = max(0.0, self._max_interval_s - elapsed)
            need_flush = (
                len(self._queue) >= self._batch_size
                or (self._queue and elapsed >= self._max_interval_s)
            )
            if not need_flush:
                self._condition.clear()
                try:
                    await asyncio.wait_for(self._condition.wait(), timeout=time_to_wait or 0.1)
                except asyncio.TimeoutError:
                    pass
                continue

            batch = self._pop_batch()
            if batch:
                await self._flush(batch)
                last_flush_at = time.monotonic()

            # Periodic stats emission
            if time.monotonic() - self._last_stats_at >= STATS_INTERVAL_S:
                LOG.info("l2 writer stats: %s", self.stats())
                self._last_stats_at = time.monotonic()

        # Final drain
        while self._queue:
            batch = self._pop_batch()
            await self._flush(batch)
        LOG.info("l2 writer final stats: %s", self.stats())

    def _pop_batch(self) -> list[L2Snapshot]:
        n = min(self._batch_size, len(self._queue))
        batch = [self._queue.popleft() for _ in range(n)]
        return batch

    async def _flush(self, batch: list[L2Snapshot]) -> None:
        if not batch or self._sb is None:
            self._n_flushed += len(batch)
            self._n_flush_batches += 1
            return
        rows = [self._to_row(s) for s in batch]
        try:
            await asyncio.to_thread(self._sync_upsert, rows)
            self._n_flushed += len(batch)
            self._n_flush_batches += 1
        except Exception as e:  # noqa: BLE001
            self._n_flush_errors += 1
            LOG.error("flush failed (%d rows): %s", len(batch), e)

    def _sync_upsert(self, rows: list[dict]) -> None:
        (
            self._sb
            .table("orderbook_snapshots_l2")
            .upsert(rows, on_conflict="venue,inst_id,exchange_ts")
            .execute()
        )

    @staticmethod
    def _to_row(snap: L2Snapshot) -> dict:
        from datetime import datetime, timezone
        exchange_ts_iso = datetime.fromtimestamp(
            snap.exchange_ts_ms / 1000.0, tz=timezone.utc,
        ).isoformat()
        return {
            "venue": snap.venue,
            "inst_id": snap.inst_id,
            "exchange_ts": exchange_ts_iso,
            "received_at": snap.received_at,
            "bids": [[p, s] for p, s in snap.bids],
            "asks": [[p, s] for p, s in snap.asks],
        }
