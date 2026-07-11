# PHASE_2_SESSION_2_LOG — Vault, OI snapshot cron wired

**Session date:** 2026-07-11
**Identity:** Vault
**Prior:** `PHASE_2_SESSION_1_LOG.md` (Phase 2 pilot burning, waiting on labels).

## Shipped

**Forward-collection for `perp_oi_pct_change_prior_24h`.** Previously flagged unrecoverable by session 1; Bitget's V2 public API exposes current OI only. Solution: snapshot every earn-catalog coin's perp OI on the same `*/15` cron as the scraper, persist to a new table, and query it at label time.

- `db/migrations/005_oi_snapshots.sql` — `earn_oi_snapshots` (coin_name, snapped_at PK) with per-coin descending index for fast anchor-time lookups.
- `src/defi_investor/oi_snapshots.py` — `fetch_current_oi(coin)` and `snapshot_universe(coins)` against `GET /api/v2/mix/market/open-interest`. Handles code=40034 (no perp) as a gap-free row with `market='none'`, oi_base NULL. 100 ms inter-call pacing; 300-coin soft cap per run.
- `src/defi_investor/db.py` — `Writer.insert_oi_snapshots()` on protocol; NoOp + Supabase impls. Supabase uses composite on_conflict `coin_name,snapped_at` for idempotence on cron re-fire.
- `src/defi_investor/scraper.py` — Post-merge step calls `snapshot_universe` over the distinct coin set in the merged catalog, persists via writer. Wrapped in try/except so Bitget transients cannot corrupt a scrape. `ScrapeResult` gained `oi_snapshots_taken`, `oi_snapshots_with_perp`, `oi_snapshots_written_remote`.
- `src/defi_investor/confounds.py` — `perp_oi_pct_change_prior_24h(coin, anchor, sb_client)` reads `earn_oi_snapshots`, picks the closest snapshot to `anchor - 24h` and to `anchor`, each within ±30 min. Returns None when either endpoint is missing (unrecoverable stays null, per METHOD §1.3 spirit). `compute_confounds` gained optional `sb_client` and now returns the 5th key.
- `scripts/backfill_labels.py` — passes `sb_client=sb` to `compute_confounds` and writes the new column into the label upsert payload. Column already exists on `earn_event_labels` from migration 003, so no schema change required there.
- Tests: 157/157 green (was 134, +23 covering fetcher happy path + all failure modes, universe dedup + cap, scraper OI wiring + non-fatal failure, writer batching + on_conflict shape, confound OI-lookup ratio + edge cases).

## What did NOT ship

- Historical backfill of the OI confound for events already sold-out before this session. Those will always show NULL for `perp_oi_pct_change_prior_24h` — this is the correct behavior per METHOD §5 (do not fabricate). Only events with anchor_ts at least 24h after the OI cron's first successful snapshot for that coin will resolve.
- OI cron cadence tuning. Currently piggybacks on the scraper's `*/15`; if Bitget rate limits become an issue on a big catalog, downshift to `*/30` or split the coin universe across runs.
- USD-notional OI. Only base-asset units stored. Sufficient for the fractional-change confound; add mark-price join if any downstream analysis needs USD.

## Operator to-do (one-shot, not code)

**Apply migration 005 to Supabase before the next scrape cron runs.**

```
psql "$SUPABASE_URL" -f db/migrations/005_oi_snapshots.sql
```

Until the migration lands, `SupabaseWriter.insert_oi_snapshots` will raise inside the try/except in `run_scrape`; the scraper stays correct but no rows land. The `oi_snapshot step failed (non-fatal)` warning in the workflow log is the tell.

## What to watch

- `earn_oi_snapshots` row count. Should grow by ~150-400 rows per `*/15` cron (roughly distinct-coin count).
- `oi_snapshots_with_perp` in the scraper's stdout JSON. Coins with no Bitget perp will produce gap rows (market='none'); this is expected but should not dominate.
- The first `perp_oi_pct_change_prior_24h` values will start appearing in `earn_event_labels` for events whose anchor_ts falls ≥ 24h after 2026-07-11's first successful scrape run. So: earliest confound-covered event, anchor around 2026-07-12 evening UTC.

## State handoff

- Repo: 157/157 tests green. Working tree has uncommitted changes to scraper.py, db.py, confounds.py, backfill_labels.py, migration 005, oi_snapshots.py, test_oi_snapshots.py, test_confounds.py, test_scraper.py, test_db.py, and this log.
- Supabase: `earn_oi_snapshots` table not yet created — awaiting migration 005 apply.
- GH Actions: unchanged. Scraper cron picks up the new step automatically at next fire.
- No behavior change to any user-facing surface (Telegram cards, dashboard, gate report). Confound only.

## Addendum — uniqueness-weighted PSR wired

Cleared the second item on the session-1 "if impatient" list. Previously `gate_report.py` computed `average_uniqueness` and `effective_n = n_raw * uniqueness` but only reported them — the actual PSR gate check read `stats.psr_vs_zero`, which uses raw n. That is slightly optimistic when label spans overlap.

Change:
- `src/defi_investor/backtest/stats.py::psr` now accepts `n: float` (formula only needs a positive real ≥ 2). Docstring updated to state that callers may pass effective_n.
- `scripts/gate_report.py` computes `psr_effective = psr(sharpe, effective_n, skew, kurt)` and uses it for the gate-criteria check. Raw and effective PSR both print for comparison. The PASS/FAIL line for gate item 2 now reads the effective-n value.
- Tests: +3 in `test_backtest_stats.py` covering float n, monotone-toward-0.5 behavior when n shrinks, and honest 0.5 for effective n < 2.

Net corpus: 160/160 green.

## Addendum — vest-unlock scraper (tokenomist.ai SSR)

Operator overrode the session's original recommendation to defer this. Shipped the minimum-effort scraper with honest coverage limits documented in the module header.

- `db/migrations/006_next_unlocks.sql` — `earn_next_unlocks` (coin_name, snapped_at PK) with per-coin descending index + partial index on `WHERE status='tracked_with_unlock'`. **Applied to Supabase** via one-shot psycopg2 script (deleted post-apply).
- `src/defi_investor/vest_unlocks.py` — parses tokenomist's `<meta description>` regex. Status codes: `tracked_with_unlock` | `no_upcoming_unlock` | `untracked` (404) | `malformed` | `error`. `KNOWN_SLUG_OVERRIDES` seeded with 21 well-known Bitget listings whose slugs differ from lowercased symbol (ARB→arbitrum, PYTH→pyth-network, PUMP→pump-fun, etc.); operator-extendable as low-value 404s show up in the row counts.
- `src/defi_investor/scraper.py` — vest step only fires on the first cron of each hour (`now.minute < 15`), 4x cadence deflation vs OI. Non-fatal on failure.
- `src/defi_investor/db.py` — `insert_next_unlocks` on Writer protocol + NoOp + Supabase (composite on_conflict).
- `src/defi_investor/confounds.py` — `known_vest_unlock_within_3d(coin, anchor, sb_client)` returns True / False / None per METHOD §1.2 tri-state semantics (None = we don't know, distinct from False = tracked but not adjacent).
- `scripts/backfill_labels.py` — passes value into label upsert. Column already exists on `earn_event_labels` from migration 003.
- Tests: +30 across `test_vest_unlocks.py`, `test_confounds.py`, `test_scraper.py`, `test_db.py`. **186/186 green** (was 160).

### Coverage floor

Design-level caveat carried forward from research: the SSR only exposes the **single next unlock** per coin, and only for tracked tokens. Realistic coverage of primary universe events: 5-10%. Historical events sold-out before scraper start have no OI, no vest — both stay NULL forever for those, correctly.

### Additional operator to-do

None. Migration applied inline.

## Addendum — Control-arm scraper (METHOD §1.4)

Second scope-expansion in the session. Ships the data collection for the control cohort; the DiD analysis remains Phase 3 research.

- `db/migrations/007_bitget_listings.sql` — `bitget_listings` table PK on `symbol` with per-coin and per-listing_ts indexes plus a partial online index. **Applied to Supabase** (9 columns, 4 indexes verified).
- `src/defi_investor/bitget_listings.py` — fetches Bitget's authoritative `/api/v2/spot/public/symbols` endpoint (~1,175 rows in one call). Uses `openTime` as the listing timestamp. Better than parsing announcement titles — no regex against human copy, no pagination.
- `src/defi_investor/scraper.py` — daily cadence gate (`now.hour == 3 AND now.minute < 15`). Preserves `first_seen_at` via `writer.fetch_bitget_listings()` on repeat runs. Non-fatal on Bitget failure.
- `src/defi_investor/db.py` — `upsert_bitget_listings` + `fetch_bitget_listings` on Writer protocol + NoOp + Supabase (composite-friendly on `symbol` PK).
- `scripts/gate_report.py` — new descriptive "Control cohort (METHOD §1.4)" section: counts Bitget listings inside the primary time window, subtracts those with matching earn_events entries, reports the control-arm cohort size. DiD comparison of control R vs Earn R is intentionally deferred to Phase 3.
- Tests: +19 across `test_bitget_listings.py`, `test_db.py`, `test_scraper.py`. **204/204 green** (was 186).

### Deliberately deferred

- **DiD analysis** of control-arm returns using `candles.py` (7d post-listing R for each non-Earn listing vs Earn cohort primary R). This is a Phase 3 research task, not infrastructure. Per METHOD §5's "features before backtest" rule the code stays quiet until n ≥ 30 primary events exist.
- **Perp listings**. `/mix/market/contracts?productType=USDT-FUTURES` gives USDT-M perp openings but Phase 2 primary universe is spot-Earn-anchored. Perp control-arm is an easy add-on later.

## Remaining backlog

- **Paid TOTAL3 data source** (session-1 "impatient" item 3). Blocked on operator approval to spend money on CoinGecko Pro or CoinMarketCap. Until then `btc_ret_7d_prior` continues as the macro proxy.
- **Paid vest data source** (Business tier CryptoRank $149/mo or DefiLlama Pro). Would replace the SSR scraper if the primary universe ever fails on unlock-adjacent split.
- **PoolX Playwright scraper**. Session 1 deferred as "not urgent for H1 primary universe." Still deferred.

Everything else is calendar-bound.

## Next actions

Nothing to build. Second Law. Watch the row count grow. Real Phase 3 gate call remains n ≥ 30 primary universe.

— Vault, Phase 2 Session 2 close, 2026-07-11
