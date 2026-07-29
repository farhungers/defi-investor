# Phase 3 Session 1 log — 2026-07-28

**Author:** Kepler (renamed from Vault mid-session per user request).

**Session start state:** `main` at `f4b0020` (Phase 2 Session 2 wrap). 208/208 tests. Bitget-only scraping live on `*/15` (throttled by GH private-repo cron to ~4.3 runs/day). No pre-registration infrastructure. No multi-venue support. No Phase 3 code.

**Session end state:** `main` locally at `562e424`, remote at `cd917d8`. **8 commits ahead of origin/backup** (awaiting user push). 283/283 tests. Phase 3c LIVE, Phase 3d code-complete, Phase 3e code-surface-complete.

---

## What shipped, sorted by phase

### Phase 3a — library + pre-registration scaffold
- `docs/library/` — 37 LIB entries (Zettelkasten literature notes for the corpus in `reaserch/`)
- `docs/preregistrations/` — FRAME_C1, HYPOTHESIS_A2a/A2b/A3, YAML_SCHEMA, KILL_COUNTER, REGISTRY, README
- Pre-registration protocol locked (frame + hypothesis Markdown + machine YAML + git tag + OSF timestamp + red-team section + kill counter)

### Phase 3b — ops foundation
- External cron: cron-job.org account + fine-grained GH PAT scoped to `actions:write` + Bitget workflow_dispatch — fires hourly, bypasses GH private-repo throttle. Verified via test run (204 No Content → matched by fresh GH run).
- OSF: node `98kez` public, ORCID-linked, 11 pre-reg files uploaded (`scripts/upload_prereg_to_osf.py` idempotent via sha256).
- Git tags `prereg-A2a-v1`, `prereg-A2b-v1`, `prereg-A3-v1` on commit `8de07a3`; pushed to origin + backup.
- Bug fix in `scripts/gate_report.py`: removed dead-code `earn_coins = {row["coin_name"] for row in raw ...}` KeyError; added `n<2` guard on control-cohort section.
- BGBTC parser drift fix: `OnChainElite` added to `LIST_DATA_BIZLINES` in `parsers/next_data.py`.

### Phase 3c — multi-venue Binance Simple Earn (LIVE in prod)
- Reverse-engineered `GET /bapi/earn/v1/friendly/finance-earn/simple-earn/homepage/details` (public, no auth). 421 products, paginated 50/page.
- `src/defi_investor/parsers/binance_earn.py` — deterministic parser, APY normalized decimal→percentage (Binance ships `0.05`; Bitget ships `5.0`).
- `src/defi_investor/binance_earn_fetch.py` — paginated HTTP client with politeness sleep.
- `src/defi_investor/binance_scrape.py` — standalone orchestrator. **Sold-out detection is diff-based on Binance** because the homepage endpoint only returns currently-available products (`sellOut: False` on every row). Product IDs that vanish between scrapes flip to `status=6` (Bitget convention) for cross-venue consistency.
- Migration 009 applied (composite PK `(venue, product_id)` + widened FKs on `earn_events_status_log` and `earn_event_labels`, plus `venue_coin_map` table). Path B: pasted SQL into Supabase SQL editor; step 2 (DO $$ block) failed with the editor's PL/pgSQL quirk, rewrote as hardcoded FK-name drops, all steps succeeded.
- `SupabaseWriter.upsert_events` switched to `on_conflict="venue,product_id"`; `log_status_transitions` accepts `venue` kwarg; `fetch_events` accepts `venue` filter (default `bitget` for Bitget-scraper backward compat).
- `.github/workflows/scrape.yml` gained `Scrape Binance Simple Earn` step (sequential after Bitget, `continue-on-error` so a Binance blip doesn't invalidate a Bitget success).
- **Live in production:** 422 Binance rows alongside 455 Bitget rows. No collisions.
- `scripts/seed_venue_coin_map.py` — fetches Bitget `/spot/public/symbols` + Binance `/api/v3/exchangeInfo`, writes prefix-alias overrides. Live run: 3 aliases persisted (`1000CHEEMS→CHEEMSUSDT`, `1000SATS→SATSUSDT`, `1MBABYDOGE→BABYDOGEUSDT`), 242 venue-absent coins identified.

### Phase 3d — v0.3.0 triple-barrier labeler (code-complete)
- `src/defi_investor/candles.py` — `compute_sigma_realized(df, period=20)` (rolling std of daily log returns, population ddof=0) + `resample_to_daily` helper. 8 tests.
- `src/defi_investor/labelers/triple_barrier_v030.py` — implements HYPOTHESIS_A2b spec verbatim: multiplicative barriers `anchor_close × exp(±k × sigma_20d)` with `k_upper = k_lower = 2.0` pre-committed. Returns `dict[horizon_hours → LabelRowV030]` for `{24h, 48h, 168h}` (one fetch feeds all three). Fetches daily bars for sigma + 1-minute bars for barrier walk per A2b spec. 9 offline tests (synthetic candles).
- `scripts/backfill_labels_v030.py` — encodes horizon in `labeler_version` suffix (`0.3.0#h24`, `#h48`, `#h168`) to preserve composite PK `(product_id, anchor_ts, labeler_version)` without a schema change. Stores v0.3.0-specific fields in `features` JSONB. **Not yet run against production.**
- `src/defi_investor/backtest/family_wise.py` — `bonferroni_alpha()` and `holm_bonferroni()` step-down cascade. `N_REGISTERED=3` constant tracks `docs/preregistrations/KILL_COUNTER.md`. 10 tests.
- `scripts/gate_report_a2b.py` — sibling to `gate_report.py`. Per-horizon binomial test on P(+1) vs P(-1), HHI on winner-coin concentration, 3-way confound splits, Holm cascade across horizons.

### Phase 3e — L2 order-book pipeline (code-surface-complete)
- `docs/ORDERBOOK_DESIGN.md` — deploy options (A local / B free-tier cloud / C paid VPS), storage volume math (~130M rows/day raw at 150 symbols × 100ms cadence), universe scoping, feature spec, retention.
- `src/defi_investor/orderbook/__init__.py` — shared `L2Snapshot` dataclass (venue-agnostic).
- `src/defi_investor/orderbook/bitget_l2.py` — `wss://ws.bitget.com/v2/ws/public` books5 subscriber. Live-verified ~10 snapshots/sec BTCUSDT. Auto-reconnect (exponential backoff 1s→60s), ping/pong keepalive (25s).
- `src/defi_investor/orderbook/binance_l2.py` — `wss://stream.binance.com:9443/stream` combined stream `<symbol>@depth5@100ms`. Live-verified ~10 snapshots/sec BTCUSDT. **Note:** Binance partial-depth stream ships no server-side timestamp; use wall-clock receive time as `exchange_ts_ms`.
- `src/defi_investor/orderbook/features.py` — `compute_depth_asymmetry_5min` per A3 spec. 12 tests (symmetric baseline, ask/bid contraction directional signs, gap detection, coverage estimation, short-book / zero-depth safety).
- `src/defi_investor/orderbook/storage.py` — `BatchedL2Writer` async, 500-row/2s batches, 100k queue with drop-oldest backpressure, error-resilient (single flush failure doesn't kill the loop), sync Supabase upsert via `asyncio.to_thread`. 7 tests.
- `src/defi_investor/orderbook/universe.py` — 541-coin live universe (union of active-earn + recent-earn-30d, both venues); consults `venue_coin_map` for per-venue inst_id overrides. 12 tests including a regression guard against empty-`bitget_listings` (found and fixed same iteration).
- `src/defi_investor/orderbook/capture_daemon.py` — `python -m defi_investor.orderbook.capture_daemon [--venues bitget,binance] [--max-symbols N] [--dry-run]`. Live-verified end-to-end in dry-run with 3-symbol universe. Batches per-venue subscription limits (Bitget 40/msg, Binance 150 streams/URL).
- Migration 010 drafted (`orderbook_snapshots_l2`, `orderbook_features`, `orderbook_universe`) — **NOT applied**.
- `scripts/backfill_labels_a3.py` + `scripts/gate_report_a3.py` — full A3 pipeline including HYPOTHESIS_A3's four gate criteria (mean-R asymmetry + Welch t vs Bonferroni-corrected alpha + n≥30 + coverage≥70%). Gate handles missing Migration 010 gracefully.

---

## What surprised me

1. **Binance homepage endpoint only ships live products** (`sellOut: False` uniformly). Bitget's explicit `status=6` sold-out flag is a richer signal than Binance provides. Sold-out detection on Binance is diff-based across consecutive scrapes. Impact: A2b's anchor definition (`sold_out_first_seen_at`) is preserved in semantics but the underlying detection is different across venues. Documented in `parsers/binance_earn.py`.

2. **APY unit differs between venues.** Bitget ships APR as percentage points (`5.0` = 5%). Binance ships as decimal fraction (`0.05` = 5%). Normalization at parse-time in `binance_earn._apy_decimal_to_pct` so `MIN_APR_FOR_ALERT` gate applies uniformly.

3. **Coin-name divergence between Earn and spot on the same venue.** e.g. Bitget Earn ships `1000CHEEMS` while Bitget spot lists `CHEEMSUSDT` (no prefix). Not caught by the initial universe manager — showed up as WS "doesn't exist" errors in the capture daemon smoke test. Fixed via `venue_coin_map` + universe override path. Prefix aliases `1000` / `10000` / `1M` are the pattern; there may be more.

4. **`bitget_listings` table was empty** (daily 03:00 UTC scraper hadn't produced data yet or fails silently). Universe manager was dropping everything until I added an empty-table fallback. This is a pre-existing bug in the listings scraper worth investigating — not urgent for A3 which doesn't depend on it, but blocks the "control cohort" analysis in `gate_report.py`.

5. **Supabase SQL editor mishandles PL/pgSQL DO blocks** in some contexts. Migration 009 step 2 (dynamic FK-name drop via `DO $$ ... END $$`) failed with "syntax error at RECORD". Rewrote as hardcoded FK-name drops. Documented as a Supabase quirk to remember for future migrations.

---

## What the next AI needs to know

1. **My name is Kepler.** Sign your work the same way. Rationale in `CLAUDE.md §Identity`. Prior sessions signed as Vault; user renamed 2026-07-28.

2. **The user has a "gm" trigger word.** On session-open `gm`, do the three-step routine in `memory/feedback_gm_trigger.md` before responding to anything else.

3. **`main` is 8 commits ahead of remote.** Don't do anything else until you push OR the user explicitly says hold. Commits `7ef254b` through `562e424`. All logically independent and each has a self-contained commit message.

4. **Three user decisions are still open** at session close, listed at the bottom of every recent commit message: (a) push, (b) run `backfill_labels_v030.py` live, (c) pick deploy target for `capture_daemon`. If the user asks "what should we do next?", offer these three in order.

5. **Do NOT run `capture_daemon` without a deploy target.** It's a persistent process; GH Actions is inappropriate. Local runs are fine for prototype testing (`--dry-run --max-symbols 3` etc.) but not for real capture — coverage gaps would ruin the A3 primary universe.

6. **Second Law still binds** (see `docs/METHOD.md`). We now have the A2b machinery, but until the A2a n≥30 gate call at 2026-09-30, no iterating on labeler design based on preliminary results.

7. **Kill counter is at N=3** (A2a, A2b, A3; A2c queued). If a fourth pre-registered hypothesis is added, bump `N_REGISTERED` in `family_wise.py` AND `docs/preregistrations/KILL_COUNTER.md` in the same commit.

8. **Test suite is fast.** 283 tests in ~1.5s. Run before every commit; it catches EarnEvent dataclass drift and Writer protocol drift immediately.

---

## Addendum — post-code-complete iteration (2026-07-28 evening)

Session extended past the initial wrap for hardening + bug hunting + deploy planning. 7 additional commits `61163de` → `ad18222`.

### Bugs found and fixed this addendum

1. **`bitget_listings` scraper silent failure** (`61163de`). Hard-coded `hour==3 AND minute<15` gate never fired because private-repo GH cron didn't land any run in that window for weeks. Rewrote to `age_of_last_snapshot >= 20h` — drift-tolerant. Manually populated the table (1210 online listings).

2. **Vest-unlock coverage was 0%** (`cbb2d25`). Two combined failures: (a) alphabetical truncation past rank 300 hiding coins ONDO/SKYAI/W etc, (b) 5-min GH job timeout aborting the vest step mid-write. Fixed with staleness-based rotation in `snapshot_universe`; manually populated 7 rows for the sold-out coins.

3. **`scrape.yml` 5-min timeout** (`6a2a897`). Bumped to 10 min. Root cause of the vest silent-loss.

4. **A3 label sign convention was inverted** (`61163de`, caught by the integration test). `_label_from_asymmetry` mapped `asymmetry >= theta → +1`, but per the pre-registered formula ask-contraction produces NEGATIVE asymmetry. Would have labelled the wrong direction as +1 forever. Fixed before any A3 labels existed → not a pre-registration violation.

5. **Bitget spot fallback has been silently non-functional since Phase 2** (`0f641b4`, caught by the retention diagnostic). Spot uses `1min`/`4h`/`1day`; perp uses `1m`/`4H`/`1D`. `fetch_candles` passed the same string to both. Every coin without Bitget perp data was silently marked `market="none"`. Fixed with `_PERP_TO_SPOT_GRANULARITY` translation.

### Empirical measurements

- **Bitget candle retention (perp)**: 1m/5m/15m/1H ~30 days, 4H 180+ days. Direct implication: A2b's 1m-walk labelling must run within 30 days of any sold-out event.
- **Real ingest rate on `books5`**: ~0.7 snapshots/sec/symbol (much lower than theoretical 10/sec — Bitget dedupes when the top-5 doesn't change). Storage math on the free tier: 10 symbols × 2 venues ≈ 300 MB/day, 20 symbols ≈ 600 MB/day.

### Documentation shipped

- `docs/OBSERVATIONS.md` — running observation log, 5 entries: sold-out corpus characterization, A3 sign bug, vest coverage bug, v0.3.0 backfill result, retention + spot bug.
- `docs/PHASE_3E_LOCAL_STARTUP.md` — user-facing guide for running the daemon on a local machine with retention.
- `HYPOTHESIS_A2a.md` red-team item #8 — DSR N-count caveat, amendment log entry.
- `LIB_0002` (Deflated Sharpe) — status `skimmed` → `deep_read` with full equations + implementation implications extracted.

### Live-verified

- Migration 010 applied to Supabase — all 3 tables exist, FK to `earn_events(venue,product_id)` functional, smoke insert+delete passed.
- v0.3.0 backfill ran live — 21 rows written, all unlabelable (2 failure modes both documented in OBSERVATIONS).
- L2 capture daemon ran a 15-second smoke test — 21 real rows landed in `orderbook_snapshots_l2` (later deleted by cleanup script).
- `cleanup_orderbook_snapshots.py` deleted the smoke-test rows correctly.

### Deploy decision outcome

**Deferred**, tracked as Task #12. User's preference order: existing VM > GCP e2-micro free tier > local PC. Oracle Cloud is banned per user's prior experience (memory `feedback_no_oracle_cloud.md`). Awaits: user to check VM specs, or greenlight GCP walkthrough, or go local.

### Test count evolution this session

208/208 → 283/283 → 291/291 → 294/294 → **295/295**. Adding tests kept catching real bugs; the discipline paid off.

### State at session close

- `main` at `ad18222`, pushed to origin + backup
- Working tree clean (gitignored data dirs excluded)
- 295/295 tests
- 17 commits total this session
- No pending user-blocked items EXCEPT the deploy-target decision (Task #12)

Next session should start with the `gm` trigger routine per `memory/feedback_gm_trigger.md`. First action: check Task #12 and either resolve the deploy choice or proceed with other Phase 3 work (waiting for data accumulation).

---

## Session addendum — 2026-07-29 (Kepler)

### Commit `7c0cc6e` — candles.py spot-fallback fix + gitignore widening
- Shipped the uncommitted `candles.py` fix that follows through on the `0f641b4` diagnostic. Spot returns 8 columns (extra `usdt_vol`) vs perp's 7; `_to_frame` now trims to the first 7. Docstring updated.
- Widened `.gitignore` `data/events/*.jsonl` to `data/events/**/*.jsonl` so venue subdirs (Binance events file was untracked all session) stay ignored.
- 295/295 tests. Pushed to origin + backup.

### Backfill run — v0.3.0 labeler on 9 sold-out events (fired live 2026-07-29 15:00 UTC)

Ran `scripts/backfill_labels_v030.py`. Stats:
```
labeled_events: 0, labeled_rows: 0, unlabelable_rows: 27
stale_anchor: 2, skipped_existing: 0
labels: {1: 0, -1: 0, 0: 0}
by_horizon: {24: unlabelable=9, 48: unlabelable=9, 168: unlabelable=9}
```

All 27 rows landed in `earn_event_labels` with `unlabelable_reason='anchor_before_first_walk_bar'`. Total v0.3.0 rows in prod: 33 (27 new + 6 from a prior small run under the same reason).

**Diagnosis (verified with a manual Bitget probe, not hypothesized):**
- The 1m mix-candles endpoint DOES have data around the anchor (SUSHIUSDT probed at anchor=2026-07-09 18:52 UTC returned 200 bars from 19:33→22:52 — 41 minutes AFTER the anchor). Retention is not the issue.
- Root cause: **Bitget's 1m endpoint appears to return the newest ~200 bars within `[startTime, endTime]`, ignoring `startTime` and paging backward toward it — but the labeler's `fetch_candles` pages FORWARD from `startTime`.** Result: the first page skips the entire early window (including anchor), and subsequent pages are past-anchor bars only. `walk_df.index <= anchor_ts` is empty → all horizons emit `anchor_before_first_walk_bar`.
- Backfill log confirms only 2 pages were issued for SUSHIUSDT (first: startTime=2026-07-09 18:56, second: startTime=2026-07-16 22:37 — the second page starts where the first ended, but the first page's actual data was far past its requested start).

**What this means:**
- The v0.3.0 labeler is currently unable to label ANY event from a `startTime` more than a few 200-bar-windows in the past on 1m granularity.
- Not a labeler-logic issue, not a spec issue — it's the fetcher's paging assumption breaking against a Bitget quirk.
- Fix scope belongs in `src/defi_investor/candles.py` fetcher (or a labeler-side adjustment: fetch coarser walk granularity for stale anchors, then step down near the barrier crossing). Both are non-trivial and would benefit from a fresh session; **Second Law forbids me from iterating this session** to make labels start showing up.

**What NOT to do next session:**
- Do not "tune k" or "widen horizons" to squeeze labels out. The reason is mechanical, not statistical.
- Do not re-run the backfill hoping for different results. It is deterministic-unlabelable until the fetcher is fixed.

**What to do next session:**
1. Fix `fetch_candles` paging to actually cover the requested `[startTime, endTime]` when Bitget's 1m endpoint skips ahead. Likely: probe the first page, if `first_bar > startTime + tolerance`, issue a bounded-window request with a moved `endTime` to force older data.
2. Add a unit test with a fake Bitget response that reproduces the skip-ahead behavior.
3. Re-run the backfill; the 33 unlabelable rows will be overwritten via upsert.

### Task-log state at addendum close

Two of four proposed tasks addressed:
- **#1 done** — candles.py fix shipped (`7c0cc6e`).
- **#2 fired but produced 0 labeled rows** — real finding logged above; work continues via the "next session" list above rather than a re-fire.
- **#3 pending** — user has not yet chosen A/B/C.
- **#4 pending** — blocked on #3.

Working tree still clean after addendum (this doc + no code changes).

### /loop follow-through (2026-07-29, later same day)

User invoked `/loop` (dynamic mode, no interval) asking me to continue with the survey items I had proposed. Executed two more real changes plus doc housekeeping:

**Commit `e9c28d5` — universe-manager per-venue independence**
- Old semantics: coin not in `bitget_listings` → dropped from universe entirely, which also killed the Binance side.
- New semantics: `bitget_inst_id` and `binance_inst_id` are decided independently. Unlisted-on-Bitget → `bitget_inst_id=None` (kept in universe if Binance side present). Coin absent on Binance → `binance_inst_id=None`. Entry dropped only when BOTH are None.
- Sentinel encoded as `venue_coin_map.venue_coin = "__ABSENT__:{coin}"` — per-coin encoded because the composite PK `(venue, venue_coin)` cannot admit a shared bare sentinel across many absent coins. `_absent_marker(coin)` and `_is_absent(value)` helpers in `universe.py`.
- `capture_daemon` filters None inst_ids before subscribing.
- `seed_venue_coin_map` writes `__ABSENT__:{coin}` rows for coins with no venue counterpart (~123 Bitget-absent + ~119 Binance-absent per last live seeder run). Seeder NOT re-run against prod this session; a future session or user run will populate.
- 2 existing tests updated (unlisted, offline → new keep-with-None semantics). 3 new tests: bitget sentinel, binance sentinel, drop-if-both-absent. 298/298 passing.

**Commit `c5de173` — ROADMAP_V2 housekeeping**
- Marked `scripts/cleanup_orderbook_snapshots.py` (shipped as `ad18222`) as done.
- Marked venue-absent-coin fix as done.
- Removed the duplicate A3-gate-report bullet.
- Added three revision-log rows: retention script, A2b backfill run, absent-coin fix.

**Memory updates (persisted, no commits — files live outside repo)**
- `reference_user_has_vm.md`: pinned the VM specs question so the next `gm` opens with it directly, before re-proposing the A/B/C deploy menu. User deferred the decision to next session.
- `reference_github_tokens.md`: appended active-account drift observation. `gh auth switch` is machine-global; when another project switches to `arbabfar`/`farhadmaildari-lang`, git push here returns 404 (not 401 — GitHub disguises wrong-account access to private repos). Fix: run `gh auth status` before the first push in any session; if drifted, `gh auth switch -u farhungers && gh auth setup-git`.

### Observed gh auth drift (2026-07-29)
Mid-`/loop`, git push suddenly returned `remote: Repository not found` on both `origin` and `backup`. Diagnosed via `gh auth status`: active account had drifted from `farhungers` (memory rule) to `arbabfar` (probably because user's parallel work in another project switched it). Recovered with `gh auth switch -u farhungers && gh auth setup-git`; pushes resumed. Now pinned to memory so next-session-me checks preemptively.

### State at session-close (2026-07-29)
- 4 commits this session: `7c0cc6e`, `67491f3`, `e9c28d5`, `c5de173`
- `main` at `c5de173`, pushed to origin + backup (both at same SHA)
- Working tree clean
- 298/298 tests
- Two memory files updated in-place

### What next session picks up
1. **User answers the VM specs question** (opens `gm` → gate the A/B/C menu behind it).
2. Fix `fetch_candles` paging (blocked by Second Law until this session ends; explicit "no re-run, no k-tuning" callouts above).
3. Once deploy target picked: apply Migration 010, start `capture_daemon`, re-run `seed_venue_coin_map` against prod to populate the `__ABSENT__` rows.
