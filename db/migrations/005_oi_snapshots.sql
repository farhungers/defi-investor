-- Migration 005: earn_oi_snapshots for forward-collected perp open interest.
--
-- Bitget's V2 public API exposes CURRENT open interest only. To enable
-- METHOD §1.3's confound tag `perp_oi_pct_change_prior_24h` we snapshot
-- OI for every earn-catalog coin on the same */15 min cron as the scraper
-- and derive the 24h delta at label time from the accumulated table.
--
-- Apply BEFORE deploying the scraper build that calls insert_oi_snapshots.

CREATE TABLE IF NOT EXISTS earn_oi_snapshots (
    coin_name  TEXT        NOT NULL,
    snapped_at TIMESTAMPTZ NOT NULL,
    symbol     TEXT        NOT NULL,   -- e.g. LABUSDT
    market     TEXT        NOT NULL,   -- 'perp' | 'none'
    oi_base    NUMERIC,                -- Bitget openInterestList[0].size (base-asset units)
    http_status INTEGER,
    error       TEXT,
    fetched_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (coin_name, snapped_at)
);

-- Fast per-coin range scan for the confound query at anchor - 24h.
CREATE INDEX IF NOT EXISTS earn_oi_snapshots_coin_ts_idx
    ON earn_oi_snapshots (coin_name, snapped_at DESC);

-- Only-successful-perp view for hot lookups.
CREATE INDEX IF NOT EXISTS earn_oi_snapshots_perp_success_idx
    ON earn_oi_snapshots (coin_name, snapped_at DESC)
    WHERE market = 'perp' AND oi_base IS NOT NULL;
