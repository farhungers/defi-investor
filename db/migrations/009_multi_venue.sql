-- Migration 009: multi-venue support — ROADMAP_V2 Phase 3c.
--
-- Adds `venue` to earn_events, earn_events_status_log, earn_event_labels so
-- that Bitget and Binance (and future venues) can share the same tables
-- without product_id collisions. Bitget "SAVINGS_BTC_001" and Binance
-- "BTC001" are different rows: (venue, product_id) is the natural key.
--
-- Backfill semantics: every existing row is retroactively tagged
-- venue='bitget'. All existing indexes and the label FK continue to work
-- because venue is added with a default and NOT NULL is enforced only
-- after backfill.
--
-- Cross-venue coin mapping table `venue_coin_map` records equivalences:
-- Bitget BTC == Binance BTC == same underlying. In the common case the
-- coin_name string matches across venues (BTC, ETH, SOL). Edge cases
-- (PEPE vs 1000PEPE, wrapped variants) get explicit map rows.
--
-- Apply order: BEFORE deploying the Binance scraper build.
-- Reversibility: drop the added columns and the venue_coin_map table.

BEGIN;

-- ---------- earn_events ----------
ALTER TABLE earn_events
    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'bitget';

-- Existing PK is product_id (single-col). Widen to (venue, product_id)
-- via a UNIQUE constraint so we don't break the existing FK from
-- earn_events_status_log(product_id). New venues insert into the same
-- product_id namespace with venue distinguishing them.
CREATE UNIQUE INDEX IF NOT EXISTS earn_events_venue_pid_uidx
    ON earn_events (venue, product_id);

CREATE INDEX IF NOT EXISTS earn_events_venue_idx ON earn_events(venue);

-- ---------- earn_events_status_log ----------
ALTER TABLE earn_events_status_log
    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'bitget';

CREATE INDEX IF NOT EXISTS earn_events_status_log_venue_idx
    ON earn_events_status_log(venue, product_id, observed_at DESC);

-- ---------- earn_event_labels ----------
-- Labels are keyed on (product_id, anchor_ts, labeler_version). Adding
-- venue is compatible: the existing labeler only reads bitget rows so
-- backfill to 'bitget' is exact.
ALTER TABLE earn_event_labels
    ADD COLUMN IF NOT EXISTS venue TEXT NOT NULL DEFAULT 'bitget';

CREATE INDEX IF NOT EXISTS earn_event_labels_venue_idx
    ON earn_event_labels(venue, product_id);

-- ---------- venue_coin_map ----------
-- Explicit cross-venue equivalences. Most coins map by name identity so
-- rows only appear when the string form diverges.
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
