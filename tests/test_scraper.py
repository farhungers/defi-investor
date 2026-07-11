"""Scraper unit tests. No network. Uses the earning fixture as canned response."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from defi_investor.models import EarnEvent
from defi_investor.scraper import (
    load_existing_catalog,
    merge_events,
    write_catalog,
)


FIXTURE = Path(__file__).parent / "fixtures" / "earning_2026-07-09.html"


def _sample_events() -> list[EarnEvent]:
    return [
        EarnEvent(product_id="p1", coin_name="LAB", second_biz_line="Savings",
                  max_apy=365.0, status=2, sold_out=False),
        EarnEvent(product_id="p2", coin_name="OGN", second_biz_line="Savings",
                  max_apy=365.0, status=2, sold_out=False),
    ]


def test_merge_first_scrape_marks_all_new():
    fresh = _sample_events()
    merged, new_events, n_upd, trans = merge_events(
        existing={},
        fresh=fresh,
        scraped_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="data/raw/2026-07-09/22-00-00_earning.html",
        raw_capture_sha256="a" * 64,
    )
    assert len(new_events) == 2
    assert {e.product_id for e in new_events} == {"p1", "p2"}
    assert n_upd == 0
    assert trans == []
    assert merged["p1"].first_seen_at == "2026-07-09T22:00:00+00:00"
    assert merged["p1"].last_seen_at == "2026-07-09T22:00:00+00:00"


def test_merge_preserves_first_seen_on_second_scrape():
    prior = _sample_events()
    prior[0].first_seen_at = "2026-07-01T00:00:00+00:00"
    prior[0].last_seen_at = "2026-07-01T00:00:00+00:00"
    prior_dict = {p.product_id: p for p in prior}

    fresh = _sample_events()  # same events, later scrape
    merged, new_events, n_upd, trans = merge_events(
        existing=prior_dict,
        fresh=fresh,
        scraped_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="data/raw/2026-07-09/22-00-00_earning.html",
        raw_capture_sha256="b" * 64,
    )
    assert new_events == []
    assert n_upd == 2
    assert merged["p1"].first_seen_at == "2026-07-01T00:00:00+00:00"
    assert merged["p1"].last_seen_at == "2026-07-09T22:00:00+00:00"


def test_merge_detects_status_transition():
    prior = _sample_events()  # status=2
    prior_dict = {p.product_id: p for p in prior}
    prior_dict["p1"].first_seen_at = "2026-07-01T00:00:00+00:00"

    fresh = _sample_events()
    fresh[0].status = 6
    fresh[0].sold_out = True

    merged, _, _, trans = merge_events(
        existing=prior_dict,
        fresh=fresh,
        scraped_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="x",
        raw_capture_sha256="c" * 64,
    )
    assert trans == [("p1", 2, 6)]
    assert merged["p1"].sold_out_first_seen_at == "2026-07-09T22:00:00+00:00"


def test_merge_preserves_sold_out_first_seen():
    prior = _sample_events()
    prior[0].status = 6
    prior[0].sold_out = True
    prior[0].sold_out_first_seen_at = "2026-07-05T12:00:00+00:00"
    prior[0].first_seen_at = "2026-07-01T00:00:00+00:00"
    prior_dict = {p.product_id: p for p in prior}

    fresh = _sample_events()
    fresh[0].status = 6
    fresh[0].sold_out = True

    merged, _, _, trans = merge_events(
        existing=prior_dict,
        fresh=fresh,
        scraped_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="x",
        raw_capture_sha256="d" * 64,
    )
    # No transition (both scrapes saw sold_out)
    assert trans == []
    assert merged["p1"].sold_out_first_seen_at == "2026-07-05T12:00:00+00:00"


def test_write_and_reload_jsonl(tmp_path: Path):
    events_path = tmp_path / "events.jsonl"
    fresh = _sample_events()
    # Set required provenance-ish fields
    for e in fresh:
        e.first_seen_at = "2026-07-09T22:00:00+00:00"
        e.last_seen_at = "2026-07-09T22:00:00+00:00"
        e.raw_capture_path = "x"
        e.raw_capture_sha256 = "d" * 64
    catalog = {e.product_id: e for e in fresh}
    write_catalog(events_path, catalog)

    loaded = load_existing_catalog(events_path)
    assert loaded == catalog


def test_write_catalog_is_sorted(tmp_path: Path):
    events_path = tmp_path / "events.jsonl"
    e1 = EarnEvent(product_id="zzz", coin_name="Z", second_biz_line="Savings")
    e2 = EarnEvent(product_id="aaa", coin_name="A", second_biz_line="Savings")
    write_catalog(events_path, {"zzz": e1, "aaa": e2})
    lines = events_path.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["product_id"] == "aaa"
    assert json.loads(lines[1])["product_id"] == "zzz"


def _stub_snapshot_universe(monkeypatch):
    """Replace both OI and vest snapshot universes with no-ops. Keeps
    tests offline regardless of the hourly-alignment branch."""
    from defi_investor import scraper as scraper_mod

    def fake(coin_names, snapped_at=None, client=None, **kw):
        return []

    monkeypatch.setattr(scraper_mod, "snapshot_universe", fake)
    monkeypatch.setattr(scraper_mod, "vest_snapshot_universe", fake)


def _freeze_now(monkeypatch, minute: int):
    """Freeze scraper's _now_utc() to a fixed minute to exercise the
    hourly-alignment gate on the vest snapshot step."""
    from datetime import datetime, timezone
    from defi_investor import scraper as scraper_mod
    frozen = datetime(2026, 7, 11, 5, minute, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(scraper_mod, "_now_utc", lambda: frozen)


def test_full_offline_flow_via_fixture(tmp_path: Path, monkeypatch):
    """Simulate a scrape without network by patching fetch_earning_html."""
    from defi_investor import scraper as scraper_mod

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)
    _stub_snapshot_universe(monkeypatch)

    result = scraper_mod.run_scrape(project_root=tmp_path)
    assert result.events_seen > 100
    assert result.events_new == result.events_seen  # first scrape, all new
    assert result.events_updated == 0
    assert result.raw_capture_path.exists()

    # Second run: nothing new, everything updated, no transitions
    result2 = scraper_mod.run_scrape(project_root=tmp_path)
    assert result2.events_new == 0
    assert result2.events_updated == result.events_seen
    assert result2.events_status_transitions == []


def test_full_offline_flow_calls_injected_writer(tmp_path: Path, monkeypatch):
    """The scraper should mirror the merged catalog + transitions to the writer."""
    from defi_investor import scraper as scraper_mod
    from defi_investor.models import EarnEvent

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)
    _stub_snapshot_universe(monkeypatch)

    class RecordingWriter:
        def __init__(self):
            self.upserts: list[list[EarnEvent]] = []
            self.transitions: list[tuple[list, str, str]] = []
            self.oi_rows: list[list[dict]] = []

        def upsert_events(self, events):
            batch = list(events)
            self.upserts.append(batch)
            return len(batch)

        def log_status_transitions(self, transitions, observed_at, raw_capture_sha256):
            self.transitions.append((list(transitions), observed_at, raw_capture_sha256))
            return len(transitions)

        def fetch_events(self):
            return {}

        def insert_oi_snapshots(self, rows):
            batch = list(rows)
            self.oi_rows.append(batch)
            return len(batch)

    writer = RecordingWriter()
    result = scraper_mod.run_scrape(project_root=tmp_path, writer=writer)

    # First scrape: writer receives the full merged catalog, no transitions
    assert len(writer.upserts) == 1
    assert len(writer.upserts[0]) == result.events_seen
    assert result.events_upserted_remote == result.events_seen
    assert writer.transitions == [([], result.scraped_at, result.raw_capture_sha256)]
    assert result.transitions_logged_remote == 0
    # OI step ran (stubbed to return no rows here) — no snapshots persisted.
    assert result.oi_snapshots_taken == 0
    assert result.oi_snapshots_written_remote == 0


def test_scraper_persists_oi_snapshots_from_universe(tmp_path: Path, monkeypatch):
    """When snapshot_universe returns rows, the writer receives them."""
    from defi_investor import scraper as scraper_mod
    from defi_investor.oi_snapshots import OISnapshot

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)

    captured_universe: list[list[str]] = []

    def fake_snapshots(coin_names, snapped_at=None, client=None, **kw):
        coins = list(coin_names)
        captured_universe.append(coins)
        # Fake one perp hit and one gap row so both accounting counters exercise
        return [
            OISnapshot(
                coin_name=coins[0], snapped_at=snapped_at, symbol=f"{coins[0]}USDT",
                market="perp", oi_base=1000.0, http_status=200,
            ),
            OISnapshot(
                coin_name=coins[1] if len(coins) > 1 else "GHOST",
                snapped_at=snapped_at,
                symbol=(coins[1] if len(coins) > 1 else "GHOST") + "USDT",
                market="none", oi_base=None, http_status=200,
                error="api_code=40034",
            ),
        ]

    monkeypatch.setattr(scraper_mod, "snapshot_universe", fake_snapshots)
    # Vest step must also stay offline even if this minute happens to be
    # hourly-aligned. The vest wiring has its own dedicated tests.
    monkeypatch.setattr(scraper_mod, "vest_snapshot_universe",
                        lambda *a, **kw: [])

    class W:
        def __init__(self):
            self.oi_rows: list[list[dict]] = []
        def upsert_events(self, events): return sum(1 for _ in events)
        def log_status_transitions(self, *a, **k): return 0
        def fetch_events(self): return {}
        def insert_oi_snapshots(self, rows):
            batch = list(rows)
            self.oi_rows.append(batch)
            return len(batch)

    w = W()
    result = scraper_mod.run_scrape(project_root=tmp_path, writer=w)

    assert captured_universe and captured_universe[0], "universe passed to snapshot fn"
    assert result.oi_snapshots_taken == 2
    assert result.oi_snapshots_with_perp == 1
    assert result.oi_snapshots_written_remote == 2
    assert len(w.oi_rows) == 1 and len(w.oi_rows[0]) == 2
    row = w.oi_rows[0][0]
    assert set(row.keys()) >= {"coin_name", "snapped_at", "symbol",
                                "market", "oi_base", "http_status", "error"}


def test_scraper_oi_failure_is_non_fatal(tmp_path: Path, monkeypatch):
    """A raise inside snapshot_universe must not abort the scrape."""
    from defi_investor import scraper as scraper_mod

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)

    def boom(coin_names, snapped_at=None, client=None, **kw):
        raise RuntimeError("bitget rate limit")

    monkeypatch.setattr(scraper_mod, "snapshot_universe", boom)
    # Vest step must stay silent even if it happens to fire this minute.
    monkeypatch.setattr(scraper_mod, "vest_snapshot_universe",
                        lambda *a, **kw: [])

    result = scraper_mod.run_scrape(project_root=tmp_path)
    # Scrape core stayed correct; OI counters zeroed.
    assert result.events_seen > 0
    assert result.oi_snapshots_taken == 0
    assert result.oi_snapshots_written_remote == 0


def test_scraper_vest_step_runs_only_on_hourly_alignment(tmp_path: Path, monkeypatch):
    """When minute is >= 15, vest step must skip. When < 15, it must fire."""
    from defi_investor import scraper as scraper_mod
    from defi_investor.vest_unlocks import NextUnlockSnapshot

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)
    monkeypatch.setattr(scraper_mod, "snapshot_universe",
                        lambda *a, **kw: [])

    calls = {"n": 0}

    def fake_vest(coin_names, snapped_at=None, client=None, **kw):
        calls["n"] += 1
        return [NextUnlockSnapshot(
            coin_name=list(coin_names)[0], snapped_at=snapped_at,
            tokenomist_slug="x", status="tracked_with_unlock",
            next_unlock_at="2026-07-16T00:00:00+00:00",
            http_status=200,
        )]

    monkeypatch.setattr(scraper_mod, "vest_snapshot_universe", fake_vest)

    # Minute 30 → skip
    _freeze_now(monkeypatch, 30)
    r1 = scraper_mod.run_scrape(project_root=tmp_path)
    assert r1.vest_snapshot_ran is False
    assert calls["n"] == 0
    assert r1.vest_snapshots_taken == 0

    # Minute 0 → fire
    _freeze_now(monkeypatch, 0)
    r2 = scraper_mod.run_scrape(project_root=tmp_path)
    assert r2.vest_snapshot_ran is True
    assert calls["n"] == 1
    assert r2.vest_snapshots_taken == 1
    assert r2.vest_snapshots_tracked == 1


def test_scraper_vest_failure_is_non_fatal(tmp_path: Path, monkeypatch):
    """Vest step raising must not abort the scrape."""
    from defi_investor import scraper as scraper_mod

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)
    monkeypatch.setattr(scraper_mod, "snapshot_universe",
                        lambda *a, **kw: [])

    def boom(*a, **kw):
        raise RuntimeError("tokenomist down")

    monkeypatch.setattr(scraper_mod, "vest_snapshot_universe", boom)
    _freeze_now(monkeypatch, 5)

    result = scraper_mod.run_scrape(project_root=tmp_path)
    assert result.events_seen > 0
    assert result.vest_snapshot_ran is True
    assert result.vest_snapshots_taken == 0
    assert result.vest_snapshots_written_remote == 0
