-- Migration 007: bitget_listings — Control-arm cohort for METHOD §1.4.
--
-- Authoritative source: GET /api/v2/spot/public/symbols. Every row carries
-- `openTime` (ms epoch) which is the on-chain listing timestamp — the same
-- clock as our earn events. Symbols are keyed by the full trading pair
-- (e.g. GOATUSDT) but we also carry `coin_name` (baseCoin, uppercase) so
-- the confound join to earn_events is a straight equality.
--
-- METHOD §1.4 uses this table to distinguish "Earn effect" from "listing
-- effect": tokens that were listed in the same time window but did NOT get
-- an Earn program form the control arm. The DiD comparison happens in
-- gate_report at Phase 3 — this migration just makes the data present.
--
-- Apply BEFORE deploying the scraper build that calls insert_listings.

CREATE TABLE IF NOT EXISTS bitget_listings (
    symbol           TEXT        NOT NULL PRIMARY KEY,   -- e.g. GOATUSDT
    coin_name        TEXT        NOT NULL,               -- baseCoin, upper
    quote_coin       TEXT,                               -- USDT / USDC / …
    listing_ts       TIMESTAMPTZ NOT NULL,               -- Bitget openTime
    status           TEXT        NOT NULL,               -- online | offline
    off_ts           TIMESTAMPTZ,                        -- when delisted, else null
    first_seen_at    TIMESTAMPTZ NOT NULL,               -- our first observation
    last_seen_at     TIMESTAMPTZ NOT NULL,
    snapshot_source  TEXT        NOT NULL DEFAULT 'spot_symbols'
);

CREATE INDEX IF NOT EXISTS bitget_listings_coin_idx
    ON bitget_listings (coin_name);

CREATE INDEX IF NOT EXISTS bitget_listings_listing_ts_idx
    ON bitget_listings (listing_ts);

-- Fast "give me new listings in [start, end]" query for the gate report
-- control-cohort line.
CREATE INDEX IF NOT EXISTS bitget_listings_online_idx
    ON bitget_listings (listing_ts DESC)
    WHERE status = 'online';
