-- Migration 004: proxy confound columns for pilot v1.
--
-- Bitget's V2 public API has no OI history endpoint and CoinGecko's
-- free tier gates market-cap history. We store best-effort proxies
-- for backfilled events, keep the aspirational columns nullable, and
-- swap when a real data source is wired.

ALTER TABLE earn_event_labels
    ADD COLUMN IF NOT EXISTS btc_ret_7d_prior NUMERIC,
    ADD COLUMN IF NOT EXISTS perp_vol_change_prior_24h NUMERIC;
