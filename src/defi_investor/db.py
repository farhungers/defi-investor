"""Supabase writer for the earn_events catalog.

Two implementations:
- NoOpWriter: used when SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY are unset.
  The scraper stays in file-only mode. Enables the same code path in dev
  and CI without credentials.
- SupabaseWriter: batches upserts on earn_events (on_conflict=product_id)
  and appends rows to earn_events_status_log.

The client can be injected for testing so the supabase package is only
imported when actually needed.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, Optional, Protocol, Sequence

from .models import EarnEvent


LOG = logging.getLogger("defi_investor.db")


class Writer(Protocol):
    def upsert_events(self, events: Iterable[EarnEvent]) -> int: ...
    def log_status_transitions(
        self,
        transitions: Sequence[tuple[str, int, int]],
        observed_at: str,
        raw_capture_sha256: str,
        *,
        venue: str = "bitget",
    ) -> int: ...
    def fetch_events(self, *, venue: Optional[str] = "bitget") -> dict[str, EarnEvent]: ...
    def insert_oi_snapshots(self, rows: Sequence[dict]) -> int: ...
    def insert_next_unlocks(self, rows: Sequence[dict]) -> int: ...
    def upsert_bitget_listings(self, rows: Sequence[dict]) -> int: ...
    def fetch_bitget_listings(self) -> dict[str, dict]: ...


class NoOpWriter:
    """Used when Supabase creds are absent. Scraper stays file-only."""

    def upsert_events(self, events: Iterable[EarnEvent]) -> int:
        n = sum(1 for _ in events)
        LOG.debug("NoOpWriter.upsert_events: %d events discarded", n)
        return 0

    def log_status_transitions(
        self,
        transitions: Sequence[tuple[str, int, int]],
        observed_at: str,
        raw_capture_sha256: str,
        *,
        venue: str = "bitget",
    ) -> int:
        LOG.debug("NoOpWriter.log_status_transitions: %d transitions discarded (venue=%s)",
                  len(transitions), venue)
        return 0

    def fetch_events(self, *, venue: Optional[str] = "bitget") -> dict[str, EarnEvent]:
        return {}

    def insert_oi_snapshots(self, rows: Sequence[dict]) -> int:
        LOG.debug("NoOpWriter.insert_oi_snapshots: %d rows discarded", len(rows))
        return 0

    def insert_next_unlocks(self, rows: Sequence[dict]) -> int:
        LOG.debug("NoOpWriter.insert_next_unlocks: %d rows discarded", len(rows))
        return 0

    def upsert_bitget_listings(self, rows: Sequence[dict]) -> int:
        LOG.debug("NoOpWriter.upsert_bitget_listings: %d rows discarded", len(rows))
        return 0

    def fetch_bitget_listings(self) -> dict[str, dict]:
        return {}


class SupabaseWriter:
    """Batches upserts to earn_events; appends to earn_events_status_log."""

    UPSERT_BATCH_SIZE = 500

    def __init__(
        self,
        url: Optional[str] = None,
        service_role_key: Optional[str] = None,
        *,
        client=None,
    ):
        if client is None:
            if not url or not service_role_key:
                raise ValueError(
                    "SupabaseWriter requires url + service_role_key or an injected client"
                )
            # Lazy import so tests without the supabase package still run.
            from supabase import create_client  # type: ignore
            client = create_client(url, service_role_key)
        self._client = client

    @staticmethod
    def _serialize(ev: EarnEvent) -> dict:
        """Map EarnEvent -> Supabase row.

        EarnEvent.to_dict() already matches the earn_events column names
        (snake_case, ISO timestamps, JSONB-safe notes list).
        """
        return ev.to_dict()

    def upsert_events(self, events: Iterable[EarnEvent]) -> int:
        rows = [self._serialize(e) for e in events]
        if not rows:
            return 0
        # Migration 009 made (venue, product_id) the composite PK. Every
        # EarnEvent carries venue (default 'bitget'), so on_conflict lists
        # both columns. This is what makes multi-venue writes safe from
        # cross-venue product_id collision.
        n_written = 0
        for start in range(0, len(rows), self.UPSERT_BATCH_SIZE):
            batch = rows[start:start + self.UPSERT_BATCH_SIZE]
            (
                self._client
                .table("earn_events")
                .upsert(batch, on_conflict="venue,product_id")
                .execute()
            )
            n_written += len(batch)
        LOG.info("SupabaseWriter.upsert_events: %d rows in %d batch(es)",
                 n_written, (n_written + self.UPSERT_BATCH_SIZE - 1) // self.UPSERT_BATCH_SIZE)
        return n_written

    def log_status_transitions(
        self,
        transitions: Sequence[tuple[str, int, int]],
        observed_at: str,
        raw_capture_sha256: str,
        *,
        venue: str = "bitget",
    ) -> int:
        """Append transitions to earn_events_status_log.

        Post-Migration 009 the FK from status_log to earn_events is composite
        on (venue, product_id). The `venue` kwarg defaults to 'bitget' for
        backward compat with the existing Bitget scraper; the Binance scrape
        orchestrator passes venue='binance'.
        """
        if not transitions:
            return 0
        rows = [
            {
                "venue": venue,
                "product_id": pid,
                "observed_at": observed_at,
                "old_status": old,
                "new_status": new,
                "raw_capture_sha256": raw_capture_sha256,
            }
            for (pid, old, new) in transitions
        ]
        self._client.table("earn_events_status_log").insert(rows).execute()
        LOG.info("SupabaseWriter.log_status_transitions: %d rows (venue=%s)",
                 len(rows), venue)
        return len(rows)

    FETCH_PAGE_SIZE = 1000

    def fetch_events(self, *, venue: Optional[str] = "bitget") -> dict[str, EarnEvent]:
        """Rehydrate the catalog from Supabase. Used on ephemeral runners
        (GitHub Actions) where data/events/*.jsonl doesn't survive.

        Paginated so it scales past the default 1000-row Supabase cap.

        `venue`:
            - str (default 'bitget'): filter to that venue only. Result key
              is `product_id` — no venue collision because within one venue,
              product_id is unique.
            - None: fetch ALL venues. Result key remains `product_id`; if
              two venues have the same product_id, last-write-wins in the
              dict. Callers wanting a multi-venue-safe hydrate should call
              once per venue and keep results separate.
        """
        catalog: dict[str, EarnEvent] = {}
        start = 0
        while True:
            end = start + self.FETCH_PAGE_SIZE - 1
            q = self._client.table("earn_events").select("*")
            if venue is not None:
                q = q.eq("venue", venue)
            r = q.range(start, end).execute()
            rows = r.data or []
            for row in rows:
                ev = EarnEvent.from_dict(row)
                catalog[ev.product_id] = ev
            if len(rows) < self.FETCH_PAGE_SIZE:
                break
            start += self.FETCH_PAGE_SIZE
        LOG.info("SupabaseWriter.fetch_events: hydrated %d rows (venue=%s)",
                 len(catalog), venue)
        return catalog

    LISTINGS_UPSERT_BATCH_SIZE = 500

    def upsert_bitget_listings(self, rows: Sequence[dict]) -> int:
        """Upsert Bitget spot listings on the `symbol` PK.

        Preserves `first_seen_at` from prior rows by using Postgres
        upsert semantics — the Supabase client sends every column;
        first_seen_at will overwrite on repeat unless we split the
        payload. Keep it simple: the caller is responsible for passing
        the correct first_seen_at (either "the earliest we've seen"
        pulled from a prior fetch, or the current wall clock on a fresh
        row). See scraper wiring for the merge logic.
        """
        if not rows:
            return 0
        n = 0
        for start in range(0, len(rows), self.LISTINGS_UPSERT_BATCH_SIZE):
            batch = list(rows[start:start + self.LISTINGS_UPSERT_BATCH_SIZE])
            (
                self._client
                .table("bitget_listings")
                .upsert(batch, on_conflict="symbol")
                .execute()
            )
            n += len(batch)
        LOG.info("SupabaseWriter.upsert_bitget_listings: %d rows", n)
        return n

    def fetch_bitget_listings(self) -> dict[str, dict]:
        """Fetch existing listings keyed by symbol.

        Used by the scraper to preserve `first_seen_at` on repeat upserts.
        Paginated to scale past the 1000-row Supabase default.
        """
        catalog: dict[str, dict] = {}
        start = 0
        page = 1000
        while True:
            end = start + page - 1
            r = (
                self._client
                .table("bitget_listings")
                .select("symbol,first_seen_at")
                .range(start, end)
                .execute()
            )
            rows = r.data or []
            for row in rows:
                catalog[row["symbol"]] = row
            if len(rows) < page:
                break
            start += page
        return catalog

    NEXT_UNLOCKS_UPSERT_BATCH_SIZE = 500

    def insert_next_unlocks(self, rows: Sequence[dict]) -> int:
        """Upsert next-unlock snapshots on the (coin_name, snapped_at) PK."""
        if not rows:
            return 0
        n = 0
        for start in range(0, len(rows), self.NEXT_UNLOCKS_UPSERT_BATCH_SIZE):
            batch = list(rows[start:start + self.NEXT_UNLOCKS_UPSERT_BATCH_SIZE])
            (
                self._client
                .table("earn_next_unlocks")
                .upsert(batch, on_conflict="coin_name,snapped_at")
                .execute()
            )
            n += len(batch)
        LOG.info("SupabaseWriter.insert_next_unlocks: %d rows", n)
        return n

    OI_UPSERT_BATCH_SIZE = 500

    def insert_oi_snapshots(self, rows: Sequence[dict]) -> int:
        """Upsert OI snapshots on the (coin_name, snapped_at) composite PK.

        Upsert (not plain insert) so a re-run inside the same cron minute
        stays idempotent — the second write overwrites with an equal row.
        """
        if not rows:
            return 0
        n = 0
        for start in range(0, len(rows), self.OI_UPSERT_BATCH_SIZE):
            batch = list(rows[start:start + self.OI_UPSERT_BATCH_SIZE])
            (
                self._client
                .table("earn_oi_snapshots")
                .upsert(batch, on_conflict="coin_name,snapped_at")
                .execute()
            )
            n += len(batch)
        LOG.info("SupabaseWriter.insert_oi_snapshots: %d rows", n)
        return n


def build_writer(
    url: Optional[str] = None,
    service_role_key: Optional[str] = None,
) -> Writer:
    """Return SupabaseWriter if both creds present, NoOpWriter otherwise.

    Reads SUPABASE_URL / SUPABASE_SERVICE_ROLE_KEY from env if not passed.
    """
    url = url or os.environ.get("SUPABASE_URL")
    key = service_role_key or os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
    if not url or not key:
        LOG.info("Supabase credentials not set — using NoOpWriter (file-only mode)")
        return NoOpWriter()
    return SupabaseWriter(url=url, service_role_key=key)
