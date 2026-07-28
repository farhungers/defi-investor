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
from .bitget_listings import snapshot_listings as bitget_snapshot_listings
from .oi_snapshots import snapshot_universe
from .parsers.next_data import parse_earning_page
from .vest_unlocks import snapshot_universe as vest_snapshot_universe


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
    oi_snapshots_taken: int = 0
    oi_snapshots_with_perp: int = 0
    oi_snapshots_written_remote: int = 0
    vest_snapshots_taken: int = 0
    vest_snapshots_tracked: int = 0
    vest_snapshots_written_remote: int = 0
    vest_snapshot_ran: bool = False
    listings_snapshot_ran: bool = False
    listings_fetched: int = 0
    listings_written_remote: int = 0


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


# Minimum age of the last listings snapshot before we take a new one.
# 20h is a slack floor under 24h — if a scrape happens once an hour,
# the next scrape after 20h will trigger a fresh snapshot regardless
# of which hour it lands on. Prevents 24-hour dark windows when the
# 03:00 UTC cron fails or doesn't fire.
_LISTINGS_MIN_AGE_HOURS = 20


def _should_snapshot_listings(writer, now: datetime) -> bool:
    """True iff the last listings snapshot is either missing or old enough."""
    try:
        prior = writer.fetch_bitget_listings()
    except Exception:  # noqa: BLE001
        # If the fetch itself fails, be conservative and try to snapshot.
        return True
    if not prior:
        return True
    # `prior` is {symbol -> row_dict}. Take the max last_seen_at across all.
    latest_iso = ""
    for row in prior.values():
        v = row.get("last_seen_at") or ""
        if v > latest_iso:
            latest_iso = v
    if not latest_iso:
        return True
    try:
        latest = datetime.fromisoformat(latest_iso.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    age_hours = (now - latest).total_seconds() / 3600.0
    return age_hours >= _LISTINGS_MIN_AGE_HOURS


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
        # Pass the writer's Supabase client (if any) so cards can query cohort
        # context without opening a second connection.
        sb = getattr(writer, "_client", None)
        notifier = build_notifier(sb_client=sb)
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

    # OI snapshot: forward-collect current perp OI for every distinct coin in
    # the merged catalog. Enables the METHOD §1.3 confound tag
    # `perp_oi_pct_change_prior_24h` once ~24h of history accumulates.
    # Non-fatal: a Bitget rate limit or transient failure must not corrupt
    # the scrape itself.
    n_snaps = 0
    n_with_perp = 0
    n_snaps_written = 0
    distinct_coins = sorted({ev.coin_name for ev in merged.values() if ev.coin_name})
    try:
        snapshots = snapshot_universe(distinct_coins, snapped_at=scraped_at)
        n_snaps = len(snapshots)
        n_with_perp = sum(1 for s in snapshots if s.oi_base is not None)
        if snapshots:
            n_snaps_written = writer.insert_oi_snapshots([s.to_row() for s in snapshots])
        LOG.info("oi snapshot: %d coins, %d with perp, %d persisted",
                 n_snaps, n_with_perp, n_snaps_written)
    except Exception as e:
        LOG.warning("oi snapshot step failed (non-fatal): %s", e)

    # Vest-unlock snapshot: only fires on hourly-aligned runs. Vest schedules
    # change on the order of days; the 4x deflation vs OI cadence keeps the
    # /15 cron under its 5-min budget. Non-fatal on failure.
    vest_ran = False
    n_vest = 0
    n_vest_tracked = 0
    n_vest_written = 0
    if now.minute < 15:  # first cron in every hour
        vest_ran = True
        try:
            # Prioritize by staleness: never-seen coins first, then
            # oldest-snapshotted first. Fixes the alphabetical-truncation
            # bias documented in docs/OBSERVATIONS.md 2026-07-28.
            prior_last_seen: dict[str, str] = {}
            sb_for_lookup = getattr(writer, "_client", None)
            if sb_for_lookup is not None:
                try:
                    r = (
                        sb_for_lookup
                        .table("earn_next_unlocks")
                        .select("coin_name,snapped_at")
                        .execute()
                    )
                    for row in r.data or []:
                        coin = (row.get("coin_name") or "").upper()
                        ts = row.get("snapped_at") or ""
                        prior = prior_last_seen.get(coin, "")
                        if ts > prior:
                            prior_last_seen[coin] = ts
                except Exception as e:  # noqa: BLE001
                    LOG.warning("vest last-seen lookup failed; alphabetical fallback: %s", e)
            v_snaps = vest_snapshot_universe(
                distinct_coins, snapped_at=scraped_at,
                prior_last_seen=prior_last_seen or None,
            )
            n_vest = len(v_snaps)
            n_vest_tracked = sum(1 for s in v_snaps if s.status == "tracked_with_unlock")
            if v_snaps:
                n_vest_written = writer.insert_next_unlocks([s.to_row() for s in v_snaps])
            LOG.info("vest snapshot: %d coins, %d tracked with unlock, %d persisted",
                     n_vest, n_vest_tracked, n_vest_written)
        except Exception as e:
            LOG.warning("vest snapshot step failed (non-fatal): %s", e)

    # Bitget listings control-arm snapshot: fires on the first scrape of
    # each UTC day AFTER the previous snapshot is >= 20h old. Older wiring
    # gated on `hour == 3 AND minute < 15` — that made the step silently
    # skip whenever the 03:00 UTC cron didn't fire (which happened for
    # weeks when the private-repo GH cron was throttled). Non-fatal.
    listings_ran = False
    n_listings = 0
    n_listings_written = 0
    if _should_snapshot_listings(writer, now):
        listings_ran = True
        try:
            listings, stats = bitget_snapshot_listings(observed_at=scraped_at)
            n_listings = len(listings)
            if listings:
                prior = writer.fetch_bitget_listings()
                rows = [
                    l.to_row(
                        first_seen_at=(prior.get(l.symbol) or {}).get(
                            "first_seen_at", scraped_at),
                        last_seen_at=scraped_at,
                    )
                    for l in listings
                ]
                n_listings_written = writer.upsert_bitget_listings(rows)
            LOG.info("bitget listings snapshot: fetched=%d persisted=%d",
                     n_listings, n_listings_written)
        except Exception as e:
            LOG.warning("bitget listings snapshot failed (non-fatal): %s", e)

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
        oi_snapshots_taken=n_snaps,
        oi_snapshots_with_perp=n_with_perp,
        oi_snapshots_written_remote=n_snaps_written,
        vest_snapshots_taken=n_vest,
        vest_snapshots_tracked=n_vest_tracked,
        vest_snapshots_written_remote=n_vest_written,
        vest_snapshot_ran=vest_ran,
        listings_snapshot_ran=listings_ran,
        listings_fetched=n_listings,
        listings_written_remote=n_listings_written,
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
        "oi_snapshots_taken": result.oi_snapshots_taken,
        "oi_snapshots_with_perp": result.oi_snapshots_with_perp,
        "oi_snapshots_written_remote": result.oi_snapshots_written_remote,
        "vest_snapshot_ran": result.vest_snapshot_ran,
        "vest_snapshots_taken": result.vest_snapshots_taken,
        "vest_snapshots_tracked": result.vest_snapshots_tracked,
        "vest_snapshots_written_remote": result.vest_snapshots_written_remote,
        "listings_snapshot_ran": result.listings_snapshot_ran,
        "listings_fetched": result.listings_fetched,
        "listings_written_remote": result.listings_written_remote,
        "raw_capture_sha256_head": result.raw_capture_sha256[:12],
        "raw_capture_path": str(result.raw_capture_path),
    }, indent=2))


if __name__ == "__main__":
    main()
