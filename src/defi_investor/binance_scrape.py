"""Binance Simple Earn scrape orchestrator.

Parallel to `scraper.run_scrape` but venue-specific. Shares nothing with the
Bitget scrape flow beyond `EarnEvent` and the `Writer` protocol — this lets
each venue evolve independently until they naturally converge.

Pipeline:
1. Fetch all Simple Earn products via the paginated bapi endpoint.
2. Persist raw JSON capture with SHA-256 for provenance.
3. Parse to list[EarnEvent] with venue='binance'.
4. Load prior catalog from JSONL (or writer, when hydrating).
5. Diff prior vs current: product_ids in prior but not in current become
   sold-out transitions (status None -> 6 in Bitget convention). This is the
   substitute for Binance's missing explicit sold-out flag.
6. Merge into unified catalog, write JSONL, upsert to writer.

The writer's Supabase implementation currently expects single-column PK on
product_id (Migration 009 to widen this is drafted but not yet applied).
Until then, running against a live SupabaseWriter with Binance events would
risk cross-venue product_id collisions. NoOpWriter is safe.

Run:
    python -m defi_investor.binance_scrape
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .binance_earn_fetch import fetch_simple_earn_all
from .db import Writer, build_writer
from .models import EarnEvent, SCRAPER_VERSION
from .parsers.binance_earn import parse_homepage_response, VENUE


LOG = logging.getLogger("defi_investor.binance_scrape")


@dataclass
class BinanceScrapeResult:
    scraped_at: str
    raw_capture_path: Path
    raw_capture_sha256: str
    events_fetched: int
    events_new: int
    events_updated: int
    events_disappeared: int  # analogue to Bitget's sold_out transition
    events_upserted_remote: int = 0
    transitions_logged_remote: int = 0
    disappeared_product_ids: list[str] = field(default_factory=list)
    new_product_ids: list[str] = field(default_factory=list)


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".tmp_", suffix=".part")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def load_existing_binance_catalog(events_path: Path) -> dict[str, EarnEvent]:
    """Load prior Binance events keyed by product_id."""
    if not events_path.exists():
        return {}
    catalog: dict[str, EarnEvent] = {}
    with events_path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                LOG.warning("skipping malformed row in %s", events_path)
                continue
            ev = EarnEvent.from_dict(d)
            if ev.venue != VENUE:
                LOG.warning("row in binance catalog has venue=%r, ignoring", ev.venue)
                continue
            catalog[ev.product_id] = ev
    return catalog


def merge_binance_events(
    existing: dict[str, EarnEvent],
    fresh: list[EarnEvent],
    *,
    scraped_at: str,
    raw_capture_path: str,
    raw_capture_sha256: str,
) -> tuple[dict[str, EarnEvent], list[EarnEvent], int, list[str]]:
    """Merge fresh fetch into existing catalog. Return:
      merged, new_events, n_updated, disappeared_product_ids

    A "disappeared" product is one that was in `existing` but is NOT in
    `fresh` — this is Binance's equivalent of a sold-out transition, since
    the homepage endpoint drops products that are no longer available.
    """
    merged: dict[str, EarnEvent] = dict(existing)
    fresh_ids = {ev.product_id for ev in fresh}
    new_events: list[EarnEvent] = []
    n_updated = 0

    for ev in fresh:
        prior = merged.get(ev.product_id)
        ev.last_seen_at = scraped_at
        ev.raw_capture_path = raw_capture_path
        ev.raw_capture_sha256 = raw_capture_sha256
        ev.scraper_version = SCRAPER_VERSION

        if prior is None:
            ev.first_seen_at = scraped_at
            if ev.sold_out:
                ev.sold_out_first_seen_at = scraped_at
            merged[ev.product_id] = ev
            new_events.append(ev)
            continue

        ev.first_seen_at = prior.first_seen_at or scraped_at
        if ev.sold_out and prior.sold_out_first_seen_at is None:
            ev.sold_out_first_seen_at = scraped_at
        else:
            ev.sold_out_first_seen_at = prior.sold_out_first_seen_at
        merged[ev.product_id] = ev
        n_updated += 1

    # Disappearance detection: product_ids in `existing` but not in `fresh`.
    # Only count as "just disappeared" those that weren't already marked
    # sold_out (avoid re-firing on products already known to be gone).
    disappeared: list[str] = []
    for pid, prior in existing.items():
        if pid in fresh_ids:
            continue
        if prior.sold_out_first_seen_at is not None:
            continue
        # Mutate in-place: flip to sold_out semantics
        prior.sold_out = True
        prior.sold_out_first_seen_at = scraped_at
        prior.status = 6  # Bitget-convention numeric for cross-venue consistency
        prior.last_seen_at = scraped_at
        merged[pid] = prior
        disappeared.append(pid)

    return merged, new_events, n_updated, disappeared


def write_catalog(events_path: Path, catalog: dict[str, EarnEvent]) -> None:
    events_path.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(catalog.values(), key=lambda e: e.product_id)
    fd, tmp = tempfile.mkstemp(dir=str(events_path.parent), prefix=".tmp_", suffix=".jsonl.part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            for ev in ordered:
                f.write(json.dumps(ev.to_dict(), ensure_ascii=False))
                f.write("\n")
        os.replace(tmp, events_path)
    except Exception:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def run_binance_scrape(
    *,
    project_root: Path,
    writer: Optional[Writer] = None,
    write_to_writer: bool = True,
) -> BinanceScrapeResult:
    """Fetch, parse, diff-detect sold-outs, write JSONL, optionally upsert.

    `write_to_writer` defaults to True post-Migration 009: the `earn_events`
    table now has composite PK (venue, product_id), so venue='binance' rows
    coexist with venue='bitget' rows safely. Pre-migration this was False
    to prevent product_id collisions.
    """
    now = _now_utc()
    scraped_at = now.isoformat()
    day = now.strftime("%Y-%m-%d")
    hms = now.strftime("%H-%M-%S")

    raw_dir = project_root / "data" / "raw" / day
    raw_path = raw_dir / f"{hms}_binance_earn.json"
    events_path = project_root / "data" / "events" / "binance" / f"{now.strftime('%Y-%m')}.jsonl"

    LOG.info("fetching binance Simple Earn homepage (all pages)")
    raw_products = fetch_simple_earn_all()
    envelope = {"code": "000000", "data": {"list": raw_products, "total": str(len(raw_products))}}
    raw_bytes = json.dumps(envelope, separators=(",", ":")).encode("utf-8")
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    _atomic_write(raw_path, raw_bytes)
    LOG.info("raw capture: %s (sha256=%s)", raw_path, sha256[:12])

    fresh = parse_homepage_response(envelope)
    LOG.info("parsed %d fresh events", len(fresh))

    existing = load_existing_binance_catalog(events_path)
    LOG.info("loaded %d prior events from %s", len(existing), events_path.name)

    merged, new_events, n_updated, disappeared = merge_binance_events(
        existing,
        fresh,
        scraped_at=scraped_at,
        raw_capture_path=str(raw_path.relative_to(project_root).as_posix()),
        raw_capture_sha256=sha256,
    )
    write_catalog(events_path, merged)
    LOG.info(
        "catalog: %d total, %d new, %d updated, %d disappeared",
        len(merged), len(new_events), n_updated, len(disappeared),
    )

    n_upserted = 0
    n_logged = 0
    if write_to_writer:
        if writer is None:
            writer = build_writer()
        n_upserted = writer.upsert_events(merged.values())
        transitions: list[tuple[str, int, int]] = [(pid, 2, 6) for pid in disappeared]
        n_logged = writer.log_status_transitions(
            transitions, observed_at=scraped_at, raw_capture_sha256=sha256,
            venue=VENUE,
        )

    return BinanceScrapeResult(
        scraped_at=scraped_at,
        raw_capture_path=raw_path,
        raw_capture_sha256=sha256,
        events_fetched=len(fresh),
        events_new=len(new_events),
        events_updated=n_updated,
        events_disappeared=len(disappeared),
        events_upserted_remote=n_upserted,
        transitions_logged_remote=n_logged,
        disappeared_product_ids=disappeared,
        new_product_ids=[ev.product_id for ev in new_events],
    )


def main() -> int:
    from dotenv import load_dotenv
    load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    result = run_binance_scrape(project_root=Path("."))
    print("-" * 72)
    print(f"Binance scrape @ {result.scraped_at}")
    print(f"  fetched:     {result.events_fetched}")
    print(f"  new:         {result.events_new}")
    print(f"  updated:     {result.events_updated}")
    print(f"  disappeared: {result.events_disappeared}")
    if result.new_product_ids:
        sample = result.new_product_ids[:5]
        print(f"  new sample:  {sample}")
    if result.disappeared_product_ids:
        sample = result.disappeared_product_ids[:5]
        print(f"  gone sample: {sample}")
    print(f"  raw capture: {result.raw_capture_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
