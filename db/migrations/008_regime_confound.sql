-- Migration 008: METHOD §1.6 regime confound columns.
--
-- Adds the 30d BTC realized-volatility and 30d BTC return columns to
-- earn_event_labels. These populate the "regime" slot in METHOD §2.4's
-- three-way confound-split gate check. Prior gate report used a 7d
-- macro-magnitude proxy which is not a regime — this migration and the
-- companion code change fix that.

ALTER TABLE earn_event_labels
    ADD COLUMN IF NOT EXISTS btc_30d_realized_vol NUMERIC,
    ADD COLUMN IF NOT EXISTS btc_ret_30d_prior    NUMERIC;
