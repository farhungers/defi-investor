-- Migration 002: add tiers JSONB column to earn_events.
--
-- Preserves the full apyList from Bitget's SSR blob so multi-tier products
-- (stablecoin ladders like USDT: 6.16% on first 300, 1.50% on next 120M)
-- keep their tier structure instead of being flattened to max/min APR.
--
-- Motivation: docs/PHASE_1_PROBE_LOG_v2.md §5.
-- Safe: nullable-defaulted column, no data loss, no lock beyond ALTER metadata.
--
-- Apply BEFORE the OCI scraper starts its 30-day pilot. Every scrape after
-- this migration populates tiers[] for the ~10 multi-tier products.

ALTER TABLE earn_events
    ADD COLUMN IF NOT EXISTS tiers JSONB NOT NULL DEFAULT '[]'::jsonb;

-- Optional index for querying "products with 2+ tiers" without a JSONB scan.
-- Cheap on the current corpus, useful for Phase 2 cohorting.
CREATE INDEX IF NOT EXISTS earn_events_tiers_len_idx
    ON earn_events((jsonb_array_length(tiers)))
    WHERE jsonb_array_length(tiers) > 1;
