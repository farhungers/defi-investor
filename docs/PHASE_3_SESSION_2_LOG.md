# Phase 3 Session 2 log — 2026-08-03

**Author:** Kepler.

**Session start state:** `main` at `bf96f4e` (Session 4 wrap). 298/298 tests. Phase 3c LIVE, Phase 3d code-complete but A2b backfill produced 27/27 unlabelable rows (fetcher paging bug), Phase 3e code-surface-complete, Migration 010 NOT applied (blocked on user VM decision).

**Session end state:** `main` at `456b12a`, pushed to origin + backup (both at same SHA). 304/304 tests. Phase 3c LIVE, Phase 3d **LIVE (18 A2b labels landed)**, Phase 3e READY FOR VM DEPLOY (Migration 010 applied and verified).

---

## What shipped, in commit order

### `a228be3` — candles.py two-phase fetcher + backfill retry flag

Root cause of Session 4's 27/27 A2b unlabelable rows was identified in `PHASE_3_SESSION_1_LOG.md` but the fix was deferred per Second Law. Session 5 opened with that fix.

- `src/defi_investor/candles.py::_fetch_market` was single-pass forward-walk (advance `cursor = last_ts_ms + 1`). Bitget's 1m mix-candles endpoint empirically returns the *newest* ~200 bars within a wide `[startTime, endTime]` window, so the forward-walk cursor advanced past the anchor region and terminated with the early window uncovered.
- Fix: two-phase. **Phase 1** is the unchanged forward-walk (preserves 4H / oldest-first behavior). **Phase 2** activates only if the earliest returned bar is more than `2 × granularity` past `start_ms` — then iterates `[start_ms, first_ts - 1]` requests, shrinking `cursor_end` each iteration until start reached, empty response, or `_MAX_PAGES = 250` cap. Dedup by `ts_ms`; defensive break on no-progress.
- New `_granularity_to_ms` helper with a per-granularity constant table.
- Two new regression tests in `tests/test_candles.py`:
  - `test_fetch_candles_backfills_when_bitget_skips_past_start` (3-page walk pattern)
  - `test_fetch_candles_backfill_terminates_on_empty_response` (retention-floor termination, partial coverage)
- **Bonus latent bug**: `scripts/backfill_labels_v030.py::_already_labeled` used `.eq("labeler_version", LABELER_VERSION)` = `.eq("0.3.0")`, but rows are always stored as `0.3.0#h24` / `0.3.0#h48` / `0.3.0#h168` (horizon-suffix trick to preserve composite PK). So it never returned True — no rows ever skipped. Fixed to `.like("0.3.0%")`. Explains why Session 4's run showed `skipped_existing: 0` despite 6 existing rows.
- New `--retry-unlabelable` CLI flag: when set, `_already_labeled` only counts rows with `unlabelable_reason IS NULL`. Lets us overwrite the 33 stale unlabelable rows now that the fetcher works.
- 300/300 tests.

### `ef9aba3` — docs bookkeeping after backfill re-fire

Backfill was re-fired live via `python scripts/backfill_labels_v030.py --retry-unlabelable`. Result:
```
labeled_events: 6, labeled_rows: 18, unlabelable_rows: 0
stale_anchor: 2, skipped_existing: 0
labels: {1: 3, -1: 1, 0: 14}
by_horizon: {24: labeled=6, 48: labeled=6, 168: labeled=6}
```

**18 labels live in prod** (was 0), 0 unlabelable (was 27), 0 skipped (retry-unlabelable correctly bypassed the 33 stale rows). Fetcher fix validated end-to-end.

**Labels split `{+1: 3, -1: 1, 0: 14}` — 14 no-barrier-hits dominate.** Not touching k or horizons based on this — Second Law binds. Logged and moved on.

Also updated `CLAUDE.md` with a Session 5 current-state header, pushed the Session 4 header down for continuity.

### `b60a525` — seeder re-run against prod

`scripts/seed_venue_coin_map.py` had been shipped in Session 3 but the Session 4 `__ABSENT__:{coin}` sentinel additions were never re-run against prod. Fired live: **250 rows upserted**. Stats:
- Bitget: 415 direct + 3 prefix alias + 125 absent
- Binance: 421 direct + 122 absent
- 247 total `__ABSENT__` sentinels now populated

`capture_daemon` will now correctly skip venue-absent coins on subscription.

### `99d193c` — capture_daemon --max-symbols/--venues ordering fix

**Bug found via smoke test.** Two dry-run smokes were run to prove the daemon still connects live:
- Smoke #1 (`--dry-run --max-symbols 3`): 497-coin universe → capped to 3 → **0 bitget, 3 binance**. Suspicious.
- Smoke #2 (`--dry-run --venues bitget --max-symbols 3`): **0 bitget, 0 binance → exited immediately.** Real bug.

Root cause: `capture_daemon._run` applied `--max-symbols` cap *before* the venue filter. When the top 3 universe entries all had `bitget_inst_id=None` (real hazard now that 247 coins are `__ABSENT__` on one side per the seeder above), the Bitget slice collapsed to empty even though 324 Bitget-resolvable coins existed.

Fix: extracted a pure helper `_select_universe(entries, venues, max_symbols)` that filters entries lacking an inst_id in any requested venue *first*, then caps. Four new regression tests in a new `tests/test_capture_daemon.py`:
- Bitget-only + cap correctly skips Bitget-absent entries at the top
- Cap applies after filter
- Both venues requested keeps all
- Absent-on-all-requested-venues entries dropped even without cap

Re-smoked live post-fix: universe 497 → 324 Bitget-resolvable → capped to 3 (`1INCHUSDT`, `AUSDT`, `AAVEUSDT`) → WS connected to `wss://ws.bitget.com/v2/ws/public` with 3 subscribe acks. 304/304 tests.

### `b1342a4` — roadmap row for the daemon fix

One-liner doc row.

### `456b12a` — Migration 010 applied + docs

User pasted `db/migrations/010_orderbook.sql` into Supabase SQL editor. First attempt failed with `syntax error at or near 'bitget'` on line 11 — the Supabase editor rejected the `--` line comment that contained a `|` character. Second attempt with a comment-stripped variant succeeded ("Success. No rows returned"). Three tables verified via smoke query:
```
orderbook_snapshots_l2: count=0
orderbook_features: count=0
orderbook_universe: count=0
```

`capture_daemon` now has a real write target when run without `--dry-run`.

---

## What surprised me

- **The forward-walk pagination assumption had been silently wrong for the 1m endpoint since day one.** Even the 2026-07-29 diagnostic run only revealed the *symptom* (skip-ahead), not the corrective algorithm. Fixed once the API's newest-in-window behavior was accepted rather than fought.
- **The `_already_labeled` check had ALWAYS been a no-op.** It never returned True for any v0.3.0 row because the stored labeler_version always has a `#h24` etc. suffix and the check was for the bare `0.3.0`. The bug had zero user impact because backfill runs were idempotent via upsert anyway — but it also meant every backfill re-processed every event. Would have wasted API calls at larger scale.
- **`capture_daemon`'s cap-before-filter bug was invisible in dev.** Session 3-4 smokes used small universes without the venue-absent sentinels. Session 5's seeder made it visible on the first real dry-run — the fix is now under a regression test.
- **Supabase SQL editor rejected a valid line comment because it contained `|`.** Unclear if that's a parser quirk or an escaping issue, but stripping comments always works.

---

## What I upheld

- **Second Law: no iteration on the 18-label result.** Not tuning k. Not changing horizons. Not filtering the label set. Logged the `{+1: 3, -1: 1, 0: 14}` split and moved on. Gate call stays pre-committed to 2026-09-30 or n≥30.
- **No pushing without asking.** Each of the two pushes (5-commit stack, then Migration 010 doc) had explicit user greenlight.
- **`gh auth status` before push.** Caught the drift again — active account was `arbabfar` when I checked; recovered with `gh auth switch -u farhungers && gh auth setup-git`. Memory rule earned its keep on first invocation.
- **VM specs question opened `gm` per pinned memory**, before proposing the A/B/C menu. Memory then updated with confirmed specs (disk under 2 GB is fine because daemon writes to Supabase not local, RAM 300-1000 MB, Linux Py 3.11+, always-on 24/7) → VM is the deploy target.

---

## Memory updates (persisted, no commits — files live outside repo)

- `reference_user_has_vm.md`: rewrote to capture the confirmed specs. Removed the "ask before proposing A/B/C" gate (that's answered now). Added a flag about the Supabase-quota concern for daemon scaling (~10 GB/day raw at 50 symbols vs 500 MB free-tier limit) so future-me raises it before proposing full-universe capture.
- `MEMORY.md` index: replaced the "details TBD" line with the confirmed-VM one-liner.

---

## State at session-close (2026-08-03)

- 6 commits this session: `a228be3`, `ef9aba3`, `b60a525`, `99d193c`, `b1342a4`, `456b12a`
- `main` pushed through `456b12a` to both origin and backup (SHAs match)
- Working tree clean at close (this doc is the exception — will commit as the session-close artifact)
- 304/304 tests
- Two memory files updated in-place
- Prod: 18 A2b v0.3.0 labels live, 250 venue_coin_map rows, Migration 010 tables empty and ready

---

## What next session picks up

1. **Launch `capture_daemon` on the user's VM at 5-symbol pilot.** Exact command:
   ```
   python -m defi_investor.orderbook.capture_daemon --venues bitget,binance --max-symbols 5
   ```
   Once running, watch `l2 writer stats:` lines land in Supabase. Prune script (`scripts/cleanup_orderbook_snapshots.py`) should be scheduled or run manually within 24h of first data.

2. **A3 gate report smoke** — once even a few snapshots land in `orderbook_snapshots_l2`, run `python scripts/gate_report_a3.py` to verify the pipeline reports cleanly with insufficient data. Do NOT interpret any A3 numbers before n≥30 (Second Law).

3. **Storage-quota decision before scaling past ~10 symbols.** Options: paid Supabase tier, sample-rate reduction (e.g. one snapshot per second instead of per 100ms), or pre-anchor-only filtering. Design doc estimates 10 GB/day raw at 50 symbols; free tier is 500 MB.

4. **Cross-venue anchor-timing analysis** — deferred item from Phase 3c. Needs ~2 weeks of dual-venue data (we have 6+ days now); still not ready.

5. **`gate_family_rollup.py`** — join A2a + A2b + A3 p-values into one Holm cascade. Deferred until all three gates produce numbers. A3 still needs data accumulation, so not ready.

Nothing else pressing. The corpus quietly grows via the hourly cron scrape.
