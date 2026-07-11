-- Migration 006: earn_next_unlocks — forward-collected next-unlock dates
-- scraped from tokenomist.ai SSR meta description.
--
-- Coverage limitations documented in METHOD §1.2. Only tokens tokenomist
-- indexes AND whose slug matches lowercase(symbol) get a resolved row;
-- everything else lands as 'untracked' | 'no_upcoming_unlock' |
-- 'malformed' | 'error' so the confound query can distinguish "no
-- schedule" from "we don't know."
--
-- Apply BEFORE deploying the scraper build that calls insert_next_unlocks.

CREATE TABLE IF NOT EXISTS earn_next_unlocks (
    coin_name          TEXT        NOT NULL,
    snapped_at         TIMESTAMPTZ NOT NULL,
    tokenomist_slug    TEXT,                   -- guess: lower(coin_name)
    status             TEXT        NOT NULL,   -- see below
    next_unlock_at     TIMESTAMPTZ,            -- parsed from meta, NULL when unknown
    next_unlock_amount NUMERIC,                -- amount of underlying released
    next_unlock_usd    NUMERIC,                -- USD notional at page render time
    http_status        INTEGER,
    error              TEXT,
    fetched_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    PRIMARY KEY (coin_name, snapped_at)
);

-- status semantics:
--   'tracked_with_unlock'   — parsed a real date + amount from the meta.
--   'no_upcoming_unlock'    — page exists but description says "undefined".
--   'malformed'             — 200 but description regex did not match.
--   'untracked'             — 404 on the guessed slug.
--   'error'                 — network / non-200 / non-404.

CREATE INDEX IF NOT EXISTS earn_next_unlocks_coin_ts_idx
    ON earn_next_unlocks (coin_name, snapped_at DESC);

-- Fast lookup for the confound query at label time.
CREATE INDEX IF NOT EXISTS earn_next_unlocks_tracked_idx
    ON earn_next_unlocks (coin_name, next_unlock_at)
    WHERE status = 'tracked_with_unlock';
