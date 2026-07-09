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
    ) -> int: ...
    def fetch_events(self) -> dict[str, EarnEvent]: ...


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
    ) -> int:
        LOG.debug("NoOpWriter.log_status_transitions: %d transitions discarded",
                  len(transitions))
        return 0

    def fetch_events(self) -> dict[str, EarnEvent]:
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
        n_written = 0
        for start in range(0, len(rows), self.UPSERT_BATCH_SIZE):
            batch = rows[start:start + self.UPSERT_BATCH_SIZE]
            (
                self._client
                .table("earn_events")
                .upsert(batch, on_conflict="product_id")
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
    ) -> int:
        if not transitions:
            return 0
        rows = [
            {
                "product_id": pid,
                "observed_at": observed_at,
                "old_status": old,
                "new_status": new,
                "raw_capture_sha256": raw_capture_sha256,
            }
            for (pid, old, new) in transitions
        ]
        self._client.table("earn_events_status_log").insert(rows).execute()
        LOG.info("SupabaseWriter.log_status_transitions: %d rows", len(rows))
        return len(rows)

    FETCH_PAGE_SIZE = 1000

    def fetch_events(self) -> dict[str, EarnEvent]:
        """Rehydrate the catalog from Supabase. Used on ephemeral runners
        (GitHub Actions) where data/events/*.jsonl doesn't survive.

        Paginated so it scales past the default 1000-row Supabase cap.
        """
        catalog: dict[str, EarnEvent] = {}
        start = 0
        while True:
            end = start + self.FETCH_PAGE_SIZE - 1
            r = (
                self._client
                .table("earn_events")
                .select("*")
                .range(start, end)
                .execute()
            )
            rows = r.data or []
            for row in rows:
                ev = EarnEvent.from_dict(row)
                catalog[ev.product_id] = ev
            if len(rows) < self.FETCH_PAGE_SIZE:
                break
            start += self.FETCH_PAGE_SIZE
        LOG.info("SupabaseWriter.fetch_events: hydrated %d rows", len(catalog))
        return catalog


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
