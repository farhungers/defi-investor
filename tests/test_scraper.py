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
    merged, n_new, n_upd, trans = merge_events(
        existing={},
        fresh=fresh,
        scraped_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="data/raw/2026-07-09/22-00-00_earning.html",
        raw_capture_sha256="a" * 64,
    )
    assert n_new == 2
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
    merged, n_new, n_upd, trans = merge_events(
        existing=prior_dict,
        fresh=fresh,
        scraped_at="2026-07-09T22:00:00+00:00",
        raw_capture_path="data/raw/2026-07-09/22-00-00_earning.html",
        raw_capture_sha256="b" * 64,
    )
    assert n_new == 0
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


def test_full_offline_flow_via_fixture(tmp_path: Path, monkeypatch):
    """Simulate a scrape without network by patching fetch_earning_html."""
    from defi_investor import scraper as scraper_mod

    canned_html = FIXTURE.read_text(encoding="utf-8")
    monkeypatch.setattr(scraper_mod, "fetch_earning_html",
                        lambda client=None, timeout=30.0: canned_html)

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

    class RecordingWriter:
        def __init__(self):
            self.upserts: list[list[EarnEvent]] = []
            self.transitions: list[tuple[list, str, str]] = []

        def upsert_events(self, events):
            batch = list(events)
            self.upserts.append(batch)
            return len(batch)

        def log_status_transitions(self, transitions, observed_at, raw_capture_sha256):
            self.transitions.append((list(transitions), observed_at, raw_capture_sha256))
            return len(transitions)

    writer = RecordingWriter()
    result = scraper_mod.run_scrape(project_root=tmp_path, writer=writer)

    # First scrape: writer receives the full merged catalog, no transitions
    assert len(writer.upserts) == 1
    assert len(writer.upserts[0]) == result.events_seen
    assert result.events_upserted_remote == result.events_seen
    assert writer.transitions == [([], result.scraped_at, result.raw_capture_sha256)]
    assert result.transitions_logged_remote == 0
