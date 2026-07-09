-- defi-investor Supabase schema
-- Apply AFTER user greenlights Phase 1 Task 5 (Supabase integration).
-- Do NOT apply during Task 2 or Task 4 (file-only phase).

CREATE TABLE IF NOT EXISTS earn_events (
    product_id TEXT PRIMARY KEY,
    coin_name TEXT NOT NULL,
    second_biz_line TEXT NOT NULL,

    max_apy NUMERIC,
    min_apy NUMERIC,
    per_user_cap_underlying NUMERIC,

    start_time TIMESTAMPTZ,
    period_days INTEGER,
    lock_model BOOLEAN,
    period_type INTEGER,

    status INTEGER,
    sold_out BOOLEAN,

    first_seen_at TIMESTAMPTZ NOT NULL,
    last_seen_at TIMESTAMPTZ NOT NULL,
    sold_out_first_seen_at TIMESTAMPTZ,

    raw_capture_sha256 TEXT,
    raw_capture_path TEXT,
    scraper_version TEXT NOT NULL,

    data_quality TEXT NOT NULL DEFAULT 'complete',
    notes JSONB DEFAULT '[]'::jsonb
);

CREATE INDEX IF NOT EXISTS earn_events_coin_idx ON earn_events(coin_name);
CREATE INDEX IF NOT EXISTS earn_events_bizline_idx ON earn_events(second_biz_line);
CREATE INDEX IF NOT EXISTS earn_events_start_time_idx ON earn_events(start_time);
CREATE INDEX IF NOT EXISTS earn_events_first_seen_idx ON earn_events(first_seen_at);
CREATE INDEX IF NOT EXISTS earn_events_sold_out_idx ON earn_events(sold_out_first_seen_at)
    WHERE sold_out_first_seen_at IS NOT NULL;


-- Status transition log: append-only trail of status changes per product.
-- Used to reconstruct sold_out_ts precisely if the main table gets bulk-updated.
CREATE TABLE IF NOT EXISTS earn_events_status_log (
    id BIGSERIAL PRIMARY KEY,
    product_id TEXT NOT NULL REFERENCES earn_events(product_id),
    observed_at TIMESTAMPTZ NOT NULL,
    old_status INTEGER,
    new_status INTEGER NOT NULL,
    raw_capture_sha256 TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS earn_events_status_log_product_idx
    ON earn_events_status_log(product_id, observed_at DESC);
