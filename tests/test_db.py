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


def test_upsert_events_calls_upsert_with_on_conflict_product_id():
    client = FakeClient()
    w = SupabaseWriter(client=client)
    n = w.upsert_events([_mk_event(pid="p1"), _mk_event(pid="p2")])
    assert n == 2
    calls = client.tables["earn_events"].calls
    assert len(calls) == 1
    assert calls[0]["op"] == "upsert"
    assert calls[0]["on_conflict"] == "product_id"
    assert {r["product_id"] for r in calls[0]["rows"]} == {"p1", "p2"}


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
