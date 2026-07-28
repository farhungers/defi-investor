-- Migration 009: multi-venue support — ROADMAP_V2 Phase 3c.
--
-- Adds `venue` to earn_events, earn_events_status_log, earn_event_labels so
-- that Bitget and Binance (and future venues) can share the same tables
-- without product_id collisions. Bitget "BGBTC001" and a future Binance
-- "BGBTC001" (unlikely but not impossible) are different rows —
-- (venue, product_id) is the natural key.
--
-- Steps (in this order, single transaction):
--   1. Add `venue` (default 'bitget', NOT NULL) to earn_events and to both
--      child tables. All existing rows retroactively tag as venue='bitget'.
--   2. Drop the existing single-column FKs on the child tables.
--   3. Drop the existing single-column PK on earn_events.
--   4. Add composite PK on earn_events(venue, product_id).
--   5. Re-add composite FKs from child tables to the new PK.
--   6. Create venue_coin_map for cross-venue coin equivalences.
--
-- Reversibility: drop child FKs, drop composite PK, drop `venue` columns,
-- re-add single-col PK + FKs, drop venue_coin_map. Not automated; write a
-- 009_revert.sql if needed.
--
-- Apply order: BEFORE the Binance scraper is allowed to write to Supabase.
-- The current Binance scrape module `binance_scrape.py` runs with
-- write_to_writer=False by default until this migration is confirmed
-- applied. Bitget scraper is unaffected as long as its rows all carry
-- venue='bitget' (which they will, via the column default).

BEGIN;

-- ------------------------------------------------------------------
-- Step 1: add `venue` column (default 'bitget') to all three tables.
-- ------------------------------------------------------------------
ALTER TABLE earn_events
    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'bitget';

ALTER TABLE earn_events_status_log
    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'bitget';

ALTER TABLE earn_event_labels
    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'bitget';

-- ------------------------------------------------------------------
-- Step 2: drop the single-column FKs on child tables.
-- ------------------------------------------------------------------
-- The FK names are Postgres-auto-generated; look them up dynamically.
DO $$
DECLARE
    fk RECORD;
BEGIN
    FOR fk IN
        SELECT conname, conrelid::regclass AS tbl
        FROM pg_constraint
        WHERE contype = 'f'
          AND confrelid = 'earn_events'::regclass
          AND conrelid IN ('earn_events_status_log'::regclass, 'earn_event_labels'::regclass)
    LOOP
        EXECUTE format('ALTER TABLE %s DROP CONSTRAINT %I', fk.tbl, fk.conname);
    END LOOP;
END $$;

-- ------------------------------------------------------------------
-- Step 3: drop the single-column PK on earn_events.
-- ------------------------------------------------------------------
ALTER TABLE earn_events
    DROP CONSTRAINT IF EXISTS earn_events_pkey;

-- ------------------------------------------------------------------
-- Step 4: add composite PK on earn_events(venue, product_id).
-- ------------------------------------------------------------------
ALTER TABLE earn_events
    ADD CONSTRAINT earn_events_pkey PRIMARY KEY (venue, product_id);

-- ------------------------------------------------------------------
-- Step 5: re-add composite FKs from child tables to new PK.
-- ------------------------------------------------------------------
ALTER TABLE earn_events_status_log
    ADD CONSTRAINT earn_events_status_log_event_fkey
    FOREIGN KEY (venue, product_id)
    REFERENCES earn_events(venue, product_id);

ALTER TABLE earn_event_labels
    ADD CONSTRAINT earn_event_labels_event_fkey
    FOREIGN KEY (venue, product_id)
    REFERENCES earn_events(venue, product_id);

-- ------------------------------------------------------------------
-- Supporting indexes on child tables.
-- ------------------------------------------------------------------
CREATE INDEX IF NOT EXISTS earn_events_venue_idx
    ON earn_events(venue);

CREATE INDEX IF NOT EXISTS earn_events_status_log_venue_pid_idx
    ON earn_events_status_log(venue, product_id, observed_at DESC);

CREATE INDEX IF NOT EXISTS earn_event_labels_venue_pid_idx
    ON earn_event_labels(venue, product_id);

-- ------------------------------------------------------------------
-- Step 6: cross-venue coin equivalence table.
-- ------------------------------------------------------------------
-- Explicit map for the minority case where the same underlying trades under
-- different string forms across venues (PEPE vs 1000PEPE, wrapped variants,
-- venue-specific tickers). The default heuristic is string equality on
-- coin_name; rows in this table override that heuristic.
CREATE TABLE IF NOT EXISTS venue_coin_map (
    canonical_coin  TEXT NOT NULL,           -- our chosen name, uppercase
    venue           TEXT NOT NULL,           -- bitget | binance | ...
    venue_coin      TEXT NOT NULL,           -- name as it appears on that venue
    notes           TEXT,
    PRIMARY KEY (venue, venue_coin)
);

CREATE INDEX IF NOT EXISTS venue_coin_map_canonical_idx
    ON venue_coin_map(canonical_coin);

COMMIT;
