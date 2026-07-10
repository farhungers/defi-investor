-- Migration 003: earn_event_labels table for Phase 2 labeler.
--
-- Design: PHASE_2_PLAN §6 and METHOD §5. Composite primary key includes
-- labeler_version so a labeler bump never overwrites prior rows — Phase 2
-- keeps history of every labeler generation.
--
-- Apply BEFORE running scripts/backfill_labels.py or the label workflow.

CREATE TABLE IF NOT EXISTS earn_event_labels (
    product_id TEXT NOT NULL REFERENCES earn_events(product_id),
    anchor_ts TIMESTAMPTZ NOT NULL,
    labeler_version TEXT NOT NULL,

    label INTEGER,                        -- +1 dumped, -1 pumped, 0 T2, NULL unresolved
    realized_r NUMERIC,
    barrier_hit TEXT,                     -- 'T1_UP' | 'T1_DOWN' | 'T2' | NULL
    barrier_hit_ts TIMESTAMPTZ,
    anchor_close_price NUMERIC,
    atr_4h_at_anchor NUMERIC,
    market TEXT,                          -- 'perp' | 'spot' | 'none'
    horizon_days INTEGER,
    k_up NUMERIC,
    k_down NUMERIC,

    unlabelable_reason TEXT,
    features JSONB NOT NULL DEFAULT '{}'::jsonb,

    -- confound tags (populated in Phase 2.5)
    within_7d_of_tge BOOLEAN,
    known_vest_unlock_within_3d BOOLEAN,
    total3_pct_change_7d NUMERIC,
    perp_oi_pct_change_prior_24h NUMERIC,
    bitget_listing_age_days INTEGER,

    -- provenance
    candles_provenance JSONB NOT NULL DEFAULT '{}'::jsonb,
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (product_id, anchor_ts, labeler_version)
);

CREATE INDEX IF NOT EXISTS earn_event_labels_anchor_idx
    ON earn_event_labels(anchor_ts);

CREATE INDEX IF NOT EXISTS earn_event_labels_resolved_idx
    ON earn_event_labels(anchor_ts)
    WHERE label IS NOT NULL;
