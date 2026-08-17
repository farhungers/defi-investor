-- Migration 011: healthchecks table for Supabase free-tier keepalive.
--
-- Supabase free-tier projects auto-pause after 7 days of no activity.
-- On 2026-08-16 the project paused because scrape.yml had been failing
-- on GH Actions billing since 2026-08-09; no writes hit Supabase for
-- >7 days and the subdomain stopped resolving.
--
-- Fix: a keepalive workflow writes one row here every 3 days. Well
-- inside the 7-day threshold with margin for one missed run.
--
-- Retention: heartbeat.py prunes rows older than 30 days on each run,
-- so the table stays trivially small.

BEGIN;

CREATE TABLE IF NOT EXISTS healthchecks (
    id      BIGSERIAL   PRIMARY KEY,
    ts      TIMESTAMPTZ NOT NULL DEFAULT now(),
    source  TEXT        NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_healthchecks_ts ON healthchecks (ts DESC);

COMMIT;
