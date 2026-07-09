"""Scraper for Bitget Earn catalog.

Phase 1 pipeline. Writes:
- data/raw/YYYY-MM-DD/HH-MM-SS_earning.html   (atomic write, provenance)
- data/events/YYYY-MM.jsonl                    (dedupe by product_id)
- Supabase earn_events + earn_events_status_log (if creds set; NoOp otherwise)

Run:
    python -m defi_investor.scraper

Or programmatically:
    from defi_investor.scraper import run_scrape
    result = run_scrape(project_root=Path("."))
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

import httpx

from .db import Writer, build_writer
from .models import EarnEvent, SCRAPER_VERSION
from .notifier import Notifier, build_notifier, dispatch_scrape_notifications
from .parsers.next_data import parse_earning_page


LOG = logging.getLogger("defi_investor.scraper")
EARNING_URL = "https://www.bitget.com/asia/earning"
USER_AGENT = f"defi-investor-research/{SCRAPER_VERSION} (research; contact via GitHub)"
BROWSER_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


@dataclass
class ScrapeResult:
    scraped_at: str  # ISO 8601 UTC
    raw_capture_path: Path
    raw_capture_sha256: str
    events_seen: int
    events_new: int
    events_updated: int
    events_status_transitions: list[tuple[str, int, int]]  # (product_id, old, new)
    events_upserted_remote: int = 0
    transitions_logged_remote: int = 0
    alerts_sent: dict[str, int] = None  # {"new": _, "sold_out": _, "reopened": _}


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


def fetch_earning_html(client: Optional[httpx.Client] = None, timeout: float = 30.0) -> str:
    """Fetch the Earn landing page HTML. Uses a browser UA to get SSR content."""
    close_after = client is None
    if client is None:
        client = httpx.Client(
            headers={
                "User-Agent": BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=timeout,
            follow_redirects=True,
        )
    try:
        r = client.get(EARNING_URL)
        r.raise_for_status()
        return r.text
    finally:
        if close_after:
            client.close()


def load_existing_catalog(events_path: Path) -> dict[str, EarnEvent]:
    """Load the existing events catalog keyed by product_id from JSONL."""
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
                LOG.warning("skipping malformed JSONL row in %s", events_path)
                continue
            ev = EarnEvent.from_dict(d)
            # Later rows for the same product overwrite earlier rows (last-write-wins)
            catalog[ev.product_id] = ev
    return catalog


def merge_events(
    existing: dict[str, EarnEvent],
    fresh: Iterable[EarnEvent],
    *,
    scraped_at: str,
    raw_capture_path: str,
    raw_capture_sha256: str,
) -> tuple[dict[str, EarnEvent], list[EarnEvent], int, list[tuple[str, int, int]]]:
    """Merge fresh scrape into existing catalog.

    Returns (merged, new_events, n_updated, transitions):
    - merged: full merged catalog dict, keyed by product_id
    - new_events: list of events seen for the first time this scrape
    - n_updated: number of existing rows updated
    - transitions: (product_id, old_status, new_status) for status changes
    """
    merged = dict(existing)
    new_events: list[EarnEvent] = []
    n_updated = 0
    transitions: list[tuple[str, int, int]] = []

    for ev in fresh:
        prior = merged.get(ev.product_id)
        # Attach provenance to every observed event
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

        # Preserve first_seen and sold_out_first_seen from prior observation
        ev.first_seen_at = prior.first_seen_at or scraped_at

        # Detect status transitions
        old_status = prior.status
        new_status = ev.status
        if old_status is not None and new_status is not None and old_status != new_status:
            transitions.append((ev.product_id, old_status, new_status))

        # First moment we saw sold_out
        if ev.sold_out and prior.sold_out_first_seen_at is None:
            ev.sold_out_first_seen_at = scraped_at
        else:
            ev.sold_out_first_seen_at = prior.sold_out_first_seen_at

        # If nothing meaningful changed (same status, apy, notes), we still bump last_seen
        merged[ev.product_id] = ev
        n_updated += 1

    return merged, new_events, n_updated, transitions


def write_catalog(events_path: Path, catalog: dict[str, EarnEvent]) -> None:
    """Rewrite the JSONL catalog with the merged state.

    Sorted by product_id for reproducibility.
    """
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


def run_scrape(
    *,
    project_root: Path,
    client: Optional[httpx.Client] = None,
    writer: Optional[Writer] = None,
    notifier: Optional[Notifier] = None,
) -> ScrapeResult:
    """Fetch, capture, parse, merge, write to file, then mirror to writer.

    `writer` defaults to build_writer() which returns a SupabaseWriter when
    credentials are set and a NoOpWriter otherwise. Injectable for tests.
    """
    now = _now_utc()
    scraped_at = now.isoformat()
    day = now.strftime("%Y-%m-%d")
    hms = now.strftime("%H-%M-%S")

    raw_dir = project_root / "data" / "raw" / day
    raw_path = raw_dir / f"{hms}_earning.html"
    events_path = project_root / "data" / "events" / f"{now.strftime('%Y-%m')}.jsonl"

    LOG.info("fetching %s", EARNING_URL)
    html = fetch_earning_html(client=client)
    raw_bytes = html.encode("utf-8")
    sha256 = hashlib.sha256(raw_bytes).hexdigest()

    _atomic_write(raw_path, raw_bytes)
    LOG.info("raw capture written: %s (sha256=%s)", raw_path, sha256[:12])

    events = parse_earning_page(html)
    LOG.info("parsed %d events", len(events))

    if writer is None:
        writer = build_writer()

    hydrated_from_writer = False
    existing = load_existing_catalog(events_path)
    if not existing:
        # Ephemeral runners (GH Actions) lose the local JSONL between runs.
        # Rehydrate prior state from the writer so first_seen_at and status
        # transitions stay accurate.
        existing = writer.fetch_events()
        if existing:
            hydrated_from_writer = True
            LOG.info("hydrated %d prior events from writer (no local JSONL)",
                     len(existing))

    merged, new_events, n_updated, transitions = merge_events(
        existing,
        events,
        scraped_at=scraped_at,
        raw_capture_path=str(raw_path.relative_to(project_root).as_posix()),
        raw_capture_sha256=sha256,
    )
    n_new = len(new_events)
    write_catalog(events_path, merged)
    LOG.info("catalog: %d total, %d new, %d updated, %d transitions",
             len(merged), n_new, n_updated, len(transitions))

    n_upserted = writer.upsert_events(merged.values())
    n_logged = writer.log_status_transitions(
        transitions, observed_at=scraped_at, raw_capture_sha256=sha256
    )

    # Alerts. Suppress on the very first cold-start run (no prior state at
    # all) so we don't fire 300+ "new listing" cards. Once catalog is
    # bootstrapped (either from JSONL or from writer hydration), alerts flow.
    alerts_sent = {"new": 0, "sold_out": 0, "reopened": 0}
    if notifier is None:
        notifier = build_notifier()
    if existing:
        # Look up the event objects for each transition so cards get full context
        transitions_with_events = [
            (merged[pid], old, new)
            for (pid, old, new) in transitions
            if pid in merged
        ]
        alerts_sent = dispatch_scrape_notifications(
            notifier,
            new_events=new_events,
            transitions_with_context=transitions_with_events,
            observed_at=scraped_at,
        )
        if any(alerts_sent.values()):
            LOG.info("alerts: %s", alerts_sent)
    else:
        LOG.info("cold start (no prior state) — alerts suppressed for this scrape")

    return ScrapeResult(
        scraped_at=scraped_at,
        raw_capture_path=raw_path,
        raw_capture_sha256=sha256,
        events_seen=len(events),
        events_new=n_new,
        events_updated=n_updated,
        events_status_transitions=transitions,
        events_upserted_remote=n_upserted,
        transitions_logged_remote=n_logged,
        alerts_sent=alerts_sent,
    )


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    # Load .env if present (no-op when the file is absent).
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:
        pass
    # project_root = parent of the `src/` folder
    project_root = Path(__file__).resolve().parent.parent.parent
    result = run_scrape(project_root=project_root)
    print(json.dumps({
        "scraped_at": result.scraped_at,
        "events_seen": result.events_seen,
        "events_new": result.events_new,
        "events_updated": result.events_updated,
        "n_transitions": len(result.events_status_transitions),
        "events_upserted_remote": result.events_upserted_remote,
        "transitions_logged_remote": result.transitions_logged_remote,
        "alerts_sent": result.alerts_sent,
        "raw_capture_sha256_head": result.raw_capture_sha256[:12],
        "raw_capture_path": str(result.raw_capture_path),
    }, indent=2))


if __name__ == "__main__":
    main()
