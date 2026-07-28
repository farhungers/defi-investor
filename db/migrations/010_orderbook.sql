-- Migration 010: orderbook snapshots + features tables (Phase 3e / A3).
--
-- Storage design per docs/ORDERBOOK_DESIGN.md:
--   orderbook_snapshots_l2   raw 100ms books5 pushes; retention TTL 24h
--                            (or 72h if disk allows; extended for gap forensics)
--   orderbook_features       per-event derived features; permanent
--
-- Volume expectation: ~10 snapshots/sec/symbol × ~150 tracked symbols
-- = 1500 rows/sec = ~130M rows/day raw. Supabase free-tier row cap is
-- generous but writes are the throttle — batched inserts required.
--
-- Retention is enforced by a nightly Supabase cron (pg_cron) that runs:
--     DELETE FROM orderbook_snapshots_l2 WHERE received_at < now() - interval '24 hours';
-- We do NOT install pg_cron here — that's a separate deploy step
-- because pg_cron requires superuser on some Supabase tiers.
--
-- Apply order: BEFORE the WS capture client is deployed to a runner
-- that will actually WRITE to Supabase. Local dry-run of bitget_l2.py
-- (stdout printing) does not require this migration.

BEGIN;

-- ------------------------------------------------------------------
-- Raw L2 snapshots (top-5 each side).
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook_snapshots_l2 (
    venue         TEXT        NOT NULL,   -- 'bitget' | 'binance'
    inst_id       TEXT        NOT NULL,   -- e.g. 'BTCUSDT'
    exchange_ts   TIMESTAMPTZ NOT NULL,   -- server-side timestamp
    received_at   TIMESTAMPTZ NOT NULL,   -- our wall clock at receive
    bids          JSONB       NOT NULL,   -- [[price_str, size_str], ...] top-5
    asks          JSONB       NOT NULL,
    PRIMARY KEY (venue, inst_id, exchange_ts)
);

CREATE INDEX IF NOT EXISTS orderbook_snapshots_l2_ingest_idx
    ON orderbook_snapshots_l2 (received_at DESC);

-- Feature-extraction access pattern: "give me all snapshots for
-- (venue, inst_id) in [anchor - 10min, anchor]". Index supports the
-- range scan on exchange_ts within a (venue, inst_id) partition.
CREATE INDEX IF NOT EXISTS orderbook_snapshots_l2_lookup_idx
    ON orderbook_snapshots_l2 (venue, inst_id, exchange_ts DESC);

-- ------------------------------------------------------------------
-- Per-event derived features (permanent; source for A3 gate).
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook_features (
    venue                     TEXT        NOT NULL,
    product_id                TEXT        NOT NULL,
    anchor_ts                 TIMESTAMPTZ NOT NULL,
    coin_name                 TEXT        NOT NULL,

    depth_asymmetry_5min      NUMERIC,
    depth_ask_pre             NUMERIC,
    depth_ask_pre_pre         NUMERIC,
    depth_bid_pre             NUMERIC,
    depth_bid_pre_pre         NUMERIC,

    n_snapshots_pre           INTEGER,
    n_snapshots_pre_pre       INTEGER,
    ws_gap_max_s              NUMERIC,
    coverage_pre              NUMERIC,

    theta_asym_used           NUMERIC     NOT NULL DEFAULT 0.5,
    label                     INTEGER,    -- +1 ask-contract / -1 bid-contract / 0 / NULL
    unlabelable_reason        TEXT,

    -- Post-anchor 24h Bitget spot return (fetched at label-time)
    r_24h                     NUMERIC,
    anchor_close_price        NUMERIC,
    post_close_price          NUMERIC,

    labeler_version           TEXT        NOT NULL,
    computed_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (venue, product_id, anchor_ts, labeler_version),

    -- FK back to earn_events via composite (venue, product_id).
    -- Migration 009 established that shape.
    FOREIGN KEY (venue, product_id) REFERENCES earn_events(venue, product_id)
);

CREATE INDEX IF NOT EXISTS orderbook_features_coin_idx
    ON orderbook_features (coin_name);

CREATE INDEX IF NOT EXISTS orderbook_features_anchor_idx
    ON orderbook_features (anchor_ts);

-- ------------------------------------------------------------------
-- Universe tracker: coins currently being captured by the WS client.
-- ------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS orderbook_universe (
    venue        TEXT        NOT NULL,
    inst_id      TEXT        NOT NULL,
    coin_name    TEXT        NOT NULL,
    added_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    removed_at   TIMESTAMPTZ,             -- null = currently tracked
    added_reason TEXT,                     -- 'active_earn' | 'recent_earn' | 'manual'
    PRIMARY KEY (venue, inst_id)
);

CREATE INDEX IF NOT EXISTS orderbook_universe_active_idx
    ON orderbook_universe (venue) WHERE removed_at IS NULL;

COMMIT;
