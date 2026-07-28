"""Tests for the L2 storage writer.

No live Supabase — uses a fake sync client that records calls.
"""
from __future__ import annotations

import asyncio

import pytest

from defi_investor.orderbook import L2Snapshot
from defi_investor.orderbook.storage import BatchedL2Writer


class _FakeExec:
    def execute(self):
        return None


class _FakeUpsert:
    def __init__(self, sink: list):
        self._sink = sink

    def upsert(self, rows, on_conflict=None):
        # Record what would have been sent
        self._sink.append({"rows": list(rows), "on_conflict": on_conflict})
        return _FakeExec()


class _FakeClient:
    def __init__(self):
        self.calls: list[dict] = []

    def table(self, name: str) -> _FakeUpsert:
        return _FakeUpsert(self.calls)


def _snap(i: int, venue: str = "bitget", inst: str = "BTCUSDT") -> L2Snapshot:
    return L2Snapshot(
        venue=venue,
        inst_id=inst,
        received_at=f"2026-07-28T12:00:{i:02d}.000+00:00",
        exchange_ts_ms=1785238500000 + i,
        bids=[(100.0 - 0.01 * j, 1.0) for j in range(5)],
        asks=[(100.0 + 0.01 * j, 1.0) for j in range(5)],
    )


async def test_start_stop_no_snapshots_no_writes():
    client = _FakeClient()
    w = BatchedL2Writer(client)
    await w.start()
    await w.stop()
    assert client.calls == []


async def test_enqueue_and_flush_by_batch_size():
    client = _FakeClient()
    w = BatchedL2Writer(client, batch_size=3, max_interval_s=10.0)
    await w.start()
    try:
        for i in range(3):
            w.enqueue(_snap(i))
        # Give the drain loop a moment to catch the batch-size trigger.
        await asyncio.sleep(0.2)
    finally:
        await w.stop()
    # One batch of 3 rows should have been flushed.
    assert len(client.calls) >= 1
    total_rows = sum(len(c["rows"]) for c in client.calls)
    assert total_rows == 3


async def test_flush_by_time_interval():
    client = _FakeClient()
    w = BatchedL2Writer(client, batch_size=1000, max_interval_s=0.15)
    await w.start()
    try:
        w.enqueue(_snap(0))
        w.enqueue(_snap(1))
        # Wait past the interval
        await asyncio.sleep(0.4)
    finally:
        await w.stop()
    total_rows = sum(len(c["rows"]) for c in client.calls)
    assert total_rows == 2


async def test_drop_oldest_when_queue_full():
    client = _FakeClient()
    # Tiny queue max so we can force overflow.
    w = BatchedL2Writer(client, queue_max=3, batch_size=100, max_interval_s=100.0)
    # Do not start drain — we want to test enqueue drop policy standalone.
    for i in range(10):
        w.enqueue(_snap(i))
    stats = w.stats()
    assert stats["queue_depth"] == 3
    assert stats["dropped"] == 7
    assert stats["enqueued"] == 10


async def test_flush_error_does_not_kill_loop():
    class _ExplodingClient(_FakeClient):
        def __init__(self):
            super().__init__()
            self._n = 0

        def table(self, name):
            self._n += 1
            if self._n == 1:
                # First flush raises
                raise RuntimeError("simulated Supabase outage")
            return super().table(name)

    client = _ExplodingClient()
    w = BatchedL2Writer(client, batch_size=2, max_interval_s=0.1)
    await w.start()
    try:
        w.enqueue(_snap(0))
        w.enqueue(_snap(1))
        await asyncio.sleep(0.2)
        # Second flush should succeed
        w.enqueue(_snap(2))
        w.enqueue(_snap(3))
        await asyncio.sleep(0.3)
    finally:
        await w.stop()
    stats = w.stats()
    assert stats["flush_errors"] >= 1
    assert stats["flushed"] >= 2   # the successful batch


async def test_final_drain_on_stop():
    client = _FakeClient()
    # Big interval, big batch — nothing should flush during run.
    w = BatchedL2Writer(client, batch_size=1000, max_interval_s=100.0)
    await w.start()
    try:
        for i in range(5):
            w.enqueue(_snap(i))
        # Immediately stop — final drain should flush the 5 buffered.
    finally:
        await w.stop()
    total_rows = sum(len(c["rows"]) for c in client.calls)
    assert total_rows == 5


async def test_row_serialisation_shape():
    client = _FakeClient()
    w = BatchedL2Writer(client, batch_size=1, max_interval_s=0.1)
    await w.start()
    try:
        w.enqueue(_snap(0))
        await asyncio.sleep(0.3)
    finally:
        await w.stop()
    row = client.calls[0]["rows"][0]
    assert row["venue"] == "bitget"
    assert row["inst_id"] == "BTCUSDT"
    assert row["exchange_ts"].endswith("+00:00")
    assert row["received_at"].endswith("+00:00")
    assert isinstance(row["bids"], list) and len(row["bids"]) == 5
    assert isinstance(row["asks"], list) and len(row["asks"]) == 5
    # bids as [[price, size], ...] lists (JSONB-friendly)
    assert all(isinstance(x, list) and len(x) == 2 for x in row["bids"])
    assert client.calls[0]["on_conflict"] == "venue,inst_id,exchange_ts"
