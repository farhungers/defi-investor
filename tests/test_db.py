"""Unit tests for the Supabase writer.

No network; injects a fake client that records calls and asserts shape.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from defi_investor.db import NoOpWriter, SupabaseWriter, build_writer
from defi_investor.models import EarnEvent


# ---------- Fake client ----------------------------------------------------

@dataclass
class FakeExecResult:
    data: list[dict] = field(default_factory=list)


class FakeQuery:
    def __init__(self, table: "FakeTable"):
        self._table = table
        self._op: str | None = None
        self._payload: Any = None
        self._on_conflict: str | None = None

    def upsert(self, rows: list[dict], on_conflict: str | None = None) -> "FakeQuery":
        self._op = "upsert"
        self._payload = rows
        self._on_conflict = on_conflict
        return self

    def insert(self, rows: list[dict]) -> "FakeQuery":
        self._op = "insert"
        self._payload = rows
        return self

    def execute(self) -> FakeExecResult:
        self._table.calls.append({
            "op": self._op,
            "rows": self._payload,
            "on_conflict": self._on_conflict,
        })
        return FakeExecResult(data=list(self._payload))


class FakeTable:
    def __init__(self, name: str):
        self.name = name
        self.calls: list[dict] = []

    def upsert(self, *args, **kwargs):
        return FakeQuery(self).upsert(*args, **kwargs)

    def insert(self, *args, **kwargs):
        return FakeQuery(self).insert(*args, **kwargs)


class FakeClient:
    def __init__(self):
        self.tables: dict[str, FakeTable] = {}

    def table(self, name: str) -> FakeTable:
        if name not in self.tables:
            self.tables[name] = FakeTable(name)
        return self.tables[name]


# ---------- Helpers --------------------------------------------------------

def _mk_event(pid: str = "p1", coin: str = "LAB", status: int = 2) -> EarnEvent:
    return EarnEvent(
        product_id=pid,
        coin_name=coin,
        second_biz_line="Savings",
        max_apy=365.0,
        status=status,
        sold_out=(status == 6),
        first_seen_at="2026-07-09T22:00:00+00:00",
        last_seen_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="data/raw/2026-07-09/22-00-00_earning.html",
        raw_capture_sha256="a" * 64,
    )


# ---------- NoOpWriter -----------------------------------------------------

def test_noop_writer_returns_zero_and_does_not_raise():
    w = NoOpWriter()
    n = w.upsert_events([_mk_event(), _mk_event(pid="p2")])
    assert n == 0
    n2 = w.log_status_transitions(
        [("p1", 2, 6)], observed_at="2026-07-09T22:00:00+00:00",
        raw_capture_sha256="a" * 64,
    )
    assert n2 == 0
    assert w.fetch_events() == {}


# ---------- build_writer ---------------------------------------------------

def test_build_writer_returns_noop_when_creds_missing(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    w = build_writer()
    assert isinstance(w, NoOpWriter)


def test_build_writer_returns_noop_when_only_one_cred_present(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://x.supabase.co")
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    w = build_writer()
    assert isinstance(w, NoOpWriter)


# ---------- SupabaseWriter -------------------------------------------------

def test_supabase_writer_requires_creds_or_client():
    with pytest.raises(ValueError):
        SupabaseWriter()


def test_upsert_events_calls_upsert_with_composite_on_conflict():
    # Post-Migration 009: composite PK on (venue, product_id).
    client = FakeClient()
    w = SupabaseWriter(client=client)
    n = w.upsert_events([_mk_event(pid="p1"), _mk_event(pid="p2")])
    assert n == 2
    calls = client.tables["earn_events"].calls
    assert len(calls) == 1
    assert calls[0]["op"] == "upsert"
    assert calls[0]["on_conflict"] == "venue,product_id"
    assert {r["product_id"] for r in calls[0]["rows"]} == {"p1", "p2"}
    # Every row must carry venue (default 'bitget' from EarnEvent dataclass).
    assert {r["venue"] for r in calls[0]["rows"]} == {"bitget"}


def test_upsert_events_serializes_full_schema():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    w.upsert_events([_mk_event(pid="p1")])
    row = client.tables["earn_events"].calls[0]["rows"][0]
    # Spot-check the columns that db/schema.sql declares NOT NULL or key
    assert row["product_id"] == "p1"
    assert row["coin_name"] == "LAB"
    assert row["second_biz_line"] == "Savings"
    assert row["max_apy"] == 365.0
    assert row["status"] == 2
    assert row["sold_out"] is False
    assert row["first_seen_at"] == "2026-07-09T22:00:00+00:00"
    assert row["last_seen_at"] == "2026-07-09T22:00:00+00:00"
    assert row["raw_capture_sha256"] == "a" * 64
    assert row["scraper_version"]
    assert row["data_quality"] == "complete"
    assert row["notes"] == []


def test_upsert_events_batches_over_limit():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    w.UPSERT_BATCH_SIZE = 100  # narrow for the test
    events = [_mk_event(pid=f"p{i}") for i in range(250)]
    n = w.upsert_events(events)
    assert n == 250
    calls = client.tables["earn_events"].calls
    assert len(calls) == 3  # 100 + 100 + 50
    assert [len(c["rows"]) for c in calls] == [100, 100, 50]


def test_upsert_events_empty_is_noop():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    n = w.upsert_events([])
    assert n == 0
    assert "earn_events" not in client.tables


def test_log_status_transitions_shape():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    n = w.log_status_transitions(
        [("p1", 2, 6), ("p2", 4, 6)],
        observed_at="2026-07-09T22:00:00+00:00",
        raw_capture_sha256="b" * 64,
    )
    assert n == 2
    calls = client.tables["earn_events_status_log"].calls
    assert len(calls) == 1
    assert calls[0]["op"] == "insert"
    rows = calls[0]["rows"]
    assert rows[0] == {
        "venue": "bitget",
        "product_id": "p1",
        "observed_at": "2026-07-09T22:00:00+00:00",
        "old_status": 2,
        "new_status": 6,
        "raw_capture_sha256": "b" * 64,
    }
    assert rows[1]["product_id"] == "p2"
    assert rows[1]["old_status"] == 4


def test_log_status_transitions_empty_is_noop():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    n = w.log_status_transitions(
        [], observed_at="2026-07-09T22:00:00+00:00", raw_capture_sha256="c" * 64,
    )
    assert n == 0
    assert "earn_events_status_log" not in client.tables


# ---------- insert_oi_snapshots -------------------------------------------

def test_noop_insert_oi_snapshots_returns_zero():
    assert NoOpWriter().insert_oi_snapshots(
        [{"coin_name": "LAB", "snapped_at": "2026-07-11T00:00:00+00:00",
          "symbol": "LABUSDT", "market": "perp", "oi_base": 1.0,
          "http_status": 200, "error": None}]
    ) == 0


def test_insert_oi_snapshots_uses_composite_on_conflict():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    rows = [
        {"coin_name": "LAB", "snapped_at": "2026-07-11T00:00:00+00:00",
         "symbol": "LABUSDT", "market": "perp", "oi_base": 10.0,
         "http_status": 200, "error": None},
        {"coin_name": "OGN", "snapped_at": "2026-07-11T00:00:00+00:00",
         "symbol": "OGNUSDT", "market": "perp", "oi_base": 20.0,
         "http_status": 200, "error": None},
    ]
    n = w.insert_oi_snapshots(rows)
    assert n == 2
    calls = client.tables["earn_oi_snapshots"].calls
    assert len(calls) == 1
    assert calls[0]["op"] == "upsert"
    assert calls[0]["on_conflict"] == "coin_name,snapped_at"


def test_insert_oi_snapshots_batches():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    w.OI_UPSERT_BATCH_SIZE = 3
    rows = [{"coin_name": f"c{i}", "snapped_at": "2026-07-11T00:00:00+00:00",
             "symbol": f"c{i}USDT", "market": "perp", "oi_base": float(i),
             "http_status": 200, "error": None} for i in range(7)]
    n = w.insert_oi_snapshots(rows)
    assert n == 7
    assert [len(c["rows"]) for c in client.tables["earn_oi_snapshots"].calls] == [3, 3, 1]


def test_insert_oi_snapshots_empty_is_noop():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    assert w.insert_oi_snapshots([]) == 0
    assert "earn_oi_snapshots" not in client.tables


# ---------- insert_next_unlocks -------------------------------------------

def test_noop_insert_next_unlocks_returns_zero():
    assert NoOpWriter().insert_next_unlocks(
        [{"coin_name": "ARB", "snapped_at": "2026-07-11T00:00:00+00:00",
          "tokenomist_slug": "arbitrum", "status": "tracked_with_unlock",
          "next_unlock_at": "2026-07-16T00:00:00+00:00",
          "next_unlock_amount": 1.0, "next_unlock_usd": 1.0,
          "http_status": 200, "error": None}]
    ) == 0


def test_insert_next_unlocks_uses_composite_on_conflict():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    rows = [
        {"coin_name": "ARB", "snapped_at": "2026-07-11T00:00:00+00:00",
         "tokenomist_slug": "arbitrum", "status": "tracked_with_unlock",
         "next_unlock_at": "2026-07-16T00:00:00+00:00",
         "next_unlock_amount": 1.0, "next_unlock_usd": 1.0,
         "http_status": 200, "error": None},
    ]
    n = w.insert_next_unlocks(rows)
    assert n == 1
    calls = client.tables["earn_next_unlocks"].calls
    assert len(calls) == 1
    assert calls[0]["op"] == "upsert"
    assert calls[0]["on_conflict"] == "coin_name,snapped_at"


def test_insert_next_unlocks_empty_is_noop():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    assert w.insert_next_unlocks([]) == 0
    assert "earn_next_unlocks" not in client.tables


# ---------- upsert_bitget_listings ---------------------------------------

def test_noop_upsert_bitget_listings_returns_zero():
    assert NoOpWriter().upsert_bitget_listings(
        [{"symbol": "GOATUSDT", "coin_name": "GOAT", "quote_coin": "USDT",
          "listing_ts": "2024-10-19T05:00:00+00:00",
          "status": "online", "off_ts": None,
          "first_seen_at": "2026-07-11T00:00:00+00:00",
          "last_seen_at": "2026-07-11T00:00:00+00:00",
          "snapshot_source": "spot_symbols"}]
    ) == 0


def test_noop_fetch_bitget_listings_returns_empty():
    assert NoOpWriter().fetch_bitget_listings() == {}


def test_upsert_bitget_listings_uses_symbol_on_conflict():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    rows = [
        {"symbol": "GOATUSDT", "coin_name": "GOAT", "quote_coin": "USDT",
         "listing_ts": "2024-10-19T05:00:00+00:00",
         "status": "online", "off_ts": None,
         "first_seen_at": "2026-07-11T00:00:00+00:00",
         "last_seen_at": "2026-07-11T00:00:00+00:00",
         "snapshot_source": "spot_symbols"},
    ]
    n = w.upsert_bitget_listings(rows)
    assert n == 1
    calls = client.tables["bitget_listings"].calls
    assert len(calls) == 1
    assert calls[0]["op"] == "upsert"
    assert calls[0]["on_conflict"] == "symbol"


def test_upsert_bitget_listings_empty_is_noop():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    assert w.upsert_bitget_listings([]) == 0
    assert "bitget_listings" not in client.tables


# ---------- fetch_events pagination -----------------------------------------

class PaginatingFakeQuery:
    def __init__(self, pages: list[list[dict]]):
        self._pages = pages
        self._select: str | None = None
        self._range: tuple[int, int] | None = None
        self._eq_filters: list[tuple[str, object]] = []

    def select(self, cols: str) -> "PaginatingFakeQuery":
        self._select = cols
        return self

    def eq(self, col: str, val: object) -> "PaginatingFakeQuery":
        self._eq_filters.append((col, val))
        return self

    def range(self, start: int, end: int) -> "PaginatingFakeQuery":
        self._range = (start, end)
        return self

    def execute(self) -> FakeExecResult:
        assert self._range is not None
        start, end = self._range
        page_size = end - start + 1
        idx = start // page_size
        page = self._pages[idx] if idx < len(self._pages) else []
        # Apply any .eq() filters
        for col, val in self._eq_filters:
            page = [r for r in page if r.get(col) == val]
        return FakeExecResult(data=page)


class PaginatingFakeClient:
    def __init__(self, pages: list[list[dict]]):
        self._pages = pages

    def table(self, name: str):
        return PaginatingFakeQuery(self._pages)


def _row(pid: str, tiers: list | None = None, venue: str = "bitget") -> dict:
    return {
        "product_id": pid,
        "coin_name": "X",
        "second_biz_line": "Savings",
        "venue": venue,
        "first_seen_at": "2026-07-09T22:00:00+00:00",
        "last_seen_at": "2026-07-09T22:00:00+00:00",
        "scraper_version": "0.2.0",
        "tiers": tiers or [],
        "notes": [],
        "data_quality": "complete",
    }


def test_fetch_events_single_page():
    pages = [[_row(f"p{i}") for i in range(3)]]
    w = SupabaseWriter(client=PaginatingFakeClient(pages))
    w.FETCH_PAGE_SIZE = 1000
    got = w.fetch_events()
    assert set(got.keys()) == {"p0", "p1", "p2"}
    assert all(isinstance(v, EarnEvent) for v in got.values())


def test_fetch_events_paginates():
    # Two full pages of 2, third partial page of 1 -> should stop after third
    pages = [
        [_row("a"), _row("b")],
        [_row("c"), _row("d")],
        [_row("e")],
    ]
    w = SupabaseWriter(client=PaginatingFakeClient(pages))
    w.FETCH_PAGE_SIZE = 2
    got = w.fetch_events()
    assert set(got.keys()) == {"a", "b", "c", "d", "e"}


def test_fetch_events_preserves_tiers():
    tiers = [{"apy": "6.16", "maxStepValue": "300", "minStepValue": "0",
              "rateLevel": 0, "productId": "usdt"}]
    pages = [[_row("usdt", tiers=tiers)]]
    w = SupabaseWriter(client=PaginatingFakeClient(pages))
    got = w.fetch_events()
    assert got["usdt"].tiers == tiers
