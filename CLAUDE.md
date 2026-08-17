# CLAUDE.md — defi-investor project

You are working on **defi-investor**, a research project (not a production trading bot yet) investigating whether Bitget's Earn program parameters and lifecycle events are correlated with pump-and-dump behavior of the underlying token, and whether that correlation is exploitable.

## Origin

Sister project to `mm-radar` (at `C:\Users\farha\OneDrive\Desktop\shitcoindetector\mm-radar\`). A previous session there (as Argus) did the initial deep logic audit on this hypothesis. That audit concluded the concept did not belong inside mm-radar because clock, universe, and lifecycle mismatch. It belongs in its own repo. This is that repo.

**Do not touch mm-radar from this project.** Sibling. Different discipline stack.

## Current state (as of 2026-08-17, Session 7 wrap)

**Phase: 3c LIVE + 3d LIVE (57 A2b labels / 19 labelable events in prod) + 3e READY FOR VM DEPLOY but DEFERRED BY USER.** 306/306 tests. `main` at pending-commit on both origin + backup after final push. Working tree clean.

**Session 7 output (2026-08-17):** 5 commits — huge session, batch-execution mode. Cleared 2 account-level blockers + 3 code bugs + shipped ops hardening.

- `0caaed7` — Supabase keepalive: `db/migrations/011_healthchecks.sql`, `scripts/heartbeat.py`, `.github/workflows/keepalive.yml` (3-day cron). Prevents free-tier auto-pause. Fixes Issue #2.
- `d58c941` — Confound audit fixes: widened `_OI_SNAPSHOT_MATCH_TOLERANCE` 30→180 min (docstring claimed 2× cadence, was 0.5×; observed p50=60 min); switched backfill filter from `sold_out=True` to `sold_out_first_seen_at IS NOT NULL` (ever-sold-out). Regression test locks tolerance.
- `d27fe57` — Binance branch in `_has_clean_anchor`: Bitget still requires status_log transition, Binance accepts `sold_out_first_seen_at` (diff-detector semantics). Unlocked 4 Binance labels immediately.
- `7c26b78` — `label_event` gates on `sold_out_first_seen_at` (not `sold_out`); re-opened Bitget products with historical anchors still labelable. +8 events. `docs/OPERATIONS.md` runbook.
- pending — bootstrap CI in `gate_report_a2b` (descriptive, not a gate criterion).

**A2b state evolution this session (Second-Law witness, no iteration on labeler):**
- Session 6 close: 6 events, 18 rows, `{+1:3, -1:1, 0:14}`
- Session 7 mid: 11 events, 33 rows after Q3 Binance fix (`d27fe57`)
- Session 7 end: **19 labelable events, 57 rows** after Q1 re-opened-product fix (`7c26b78`)
  - h=1d: `{0:14, -1:2, +1:3}`
  - h=2d: `{+1:4, 0:12, -1:3}`
  - h=7d: `{+1:7, 0:6, -1:6}`
  - by venue: bitget `{+1:14, -1:5, 0:26}`, binance `{-1:6, 0:6}`
- 28 events remain unlabelable: all old anchors (2026-07-09/10) past Bitget's 1m retention (~30-45d). Fundamentally unrecoverable, not a bug.
- Labeler code (v0.3.0, k=2.0, symmetric barriers, horizons 24/48/168h, sigma_20d on daily log returns) **unchanged all session**.

**Two account-level blockers cleared (required user action):**
1. **GitHub Actions billing block** since 2026-08-09: scraper red for 8 days. Root cause: repo private, ran out of Actions minutes. Fix: `gh repo edit --visibility public --accept-visibility-change-consequences`. User authorized.
2. **Supabase free-tier auto-pause**: 7-day inactivity → subdomain stops resolving. User restored via dashboard. Keepalive workflow prevents recurrence.

**Bug diagnoses this session (all confirmed by direct probe, not assumed):**
- `_OI_SNAPSHOT_MATCH_TOLERANCE` too tight: prod OI snapshots have p50=60 min gaps; 30-min tolerance clipped every target_before match.
- Backfill `sold_out=True` filter missed re-opened products with historical anchors.
- `_has_clean_anchor` required Bitget-only status_log; all Binance events failed.
- `label_event` bailed on `sold_out=False`; re-opened products with historical anchors were silently dropped by backfill.
- 3 Binance events (PIVX/AEUR/PYR) unlabelable due to `__ABSENT__` sentinel in venue_coin_map. Not a bug — no Bitget candle source exists.

**Read-only audits this session (all clean or documented):**
- **Anchor provenance:** 47/47 label rows have `anchor_ts == sold_out_first_seen_at`. No drift.
- **Cross-venue timestamp reconciliation:** only 1 coin (VANRY) sold-out on both venues; different products at different times, no anomaly.
- **Candle continuity sample:** 3/3 sampled old-anchor events show 0 bars in Bitget's current retention window. Confirms 30-45d 1m retention decay. Labels stored from earlier runs are unaffected.
- **Purged embargo (h=168):** default 1% embargo (~9 hours for 39-day corpus) is defensible per de Prado; primary leakage protection is the purge (interval-overlap), not embargo. No code change needed.

**Session 7 gh-auth drift:** active flipped to `arbabfar` at session open. Recovered via `gh auth switch -u farhungers && gh auth setup-git`. Memory rule keeps paying rent.

**Memory updates this session (persisted, no commits):**
- `feedback_one_issue_at_a_time.md` — user wants issues surfaced sequentially with options + recommendation, then user picks, then next. Applied for Issues #1-#5; batch-execution mode from #6 onward per explicit user direction.
- `MEMORY.md` — index updated.

**Immediate next-session behavior:**
1. **A2b n is at 19 labelable events** (across 3 horizons). Gate threshold is 30. Coverage_forecast rate suggests reachable by 2026-09-30 if scraper stays green.
2. `keepalive.yml` runs every 3 days at 06:23 UTC. If it goes red, Supabase pause returns within a week.
3. Do NOT run `gate_report_a2b.py` for interpretation. Bootstrap CI is descriptive only.
4. Queued for future sessions: fetcher paging on other endpoints (regression test), placebo cohort scaffolding (needs `PLACEBO_A2b.md` pre-reg first), A3 orderbook deploy (still user-deferred).

**Queued but not chased this session:**
- Fetcher paging regression on other endpoints
- Placebo cohort scaffolding (would need dedicated pre-registration doc)
- A3 orderbook deploy (user deferred at Session 6)
- L2 latent bug batch (blocked on A3 deploy)

## Prior current state (as of 2026-08-13, Session 6 wrap)

**Phase: 3c LIVE + 3d LIVE (18 A2b labels in prod) + 3e READY FOR VM DEPLOY but DEFERRED BY USER.** 304/304 tests. `main` at `c88c7ee` on both origin + backup. Working tree clean.

**Session 6 output (2026-08-13):** three commits. Local hardening + accuracy scaffolding under Second-Law constraint (no iteration on the A2b `{+1: 3, -1: 1, 0: 14}` split).
- `2f391ff` — L2 hardening pass. `test_drop_oldest_survives_active_drain` closes a drain-loop x drop-oldest coverage gap in `test_orderbook_storage.py`. `gate_report_a2b._load_labels_for_horizon` switched from `.eq()` to `.like(f"{prefix}%")` mirroring the Session-5 `_already_labeled` fix. New `.github/workflows/orderbook_cleanup.yml` (hourly at `:17`, 24h retention) wires the free-tier pg_cron substitute.
- `1260960` — `test_cards.py` refactor. Single `_ev(**kwargs)` factory, `OBSERVED_AT` constant, `_assert_contains` helper for better failure locality, merged cohort-with/without tests. 11 → 10 tests, 168 → 144 lines. Coverage preserved.
- `c88c7ee` — `scripts/coverage_forecast.py`. Read-only n-at-gate arithmetic for A2b. Live run: 17 sold-outs (10 bitget + 7 binance), projected event ceiling 26-58 depending on rate window (7d/14d comfortable, 30d/90d marginal). Second-Law safe: does not read labels, does not compute returns, only counts labelable events over time. Explicit caveat baked in: directional-n ≤ event-n, so ceiling isn't gate-n.

**Latent-bug audits this session (2 rounds):**
- Round 1 (cross-cutting): no repeats of the two known bug classes (suffix-blind equality, cap-before-filter). Surfaced the drain-loop test gap + gate suffix hardening (fixed in `2f391ff`).
- Round 2 (L2 pipeline unattended-runtime focus): 5 findings verified against source. 1 false positive (Binance timestamp reuse — misread; `_parse_depth5_payload` yields one snap per message). 4 real but low-priority for 5-symbol pilot (subscribe-ack loud symptom, flush observability adequate, drain-race latency-bounded, universe-refresh not urgent). **No code changes.** Discipline: don't add complexity beyond what task requires.

**VM launch DEFERRED by user (2026-08-13).** Walked through the 8-step launch sequence (SSH → clone/pull → venv → .env transfer → dry-run → tmux → verify). User said walkthrough felt confusing. Re-explained project state in plain language: A2b runs itself via hourly GH Actions scraper, VM is only needed for A3, and there's no fire. User chose "option 1: skip A3 for now." A3 gate is 2026-11-30 so there's room.

**Session 6 gh-auth drifts** — active flipped to `arbabfar` twice mid-session. Recovered both times with `gh auth switch -u farhungers && gh auth setup-git`. Memory rule keeps paying rent.

**Memory updates this session (persisted, no commits):**
- `reference_user_has_vm.md` — added "Current status" header noting the deferral. Behavioral guidance: do NOT open `gm` with "let's launch the daemon"; do NOT propose VM setup as next-session action unless user brings it up.
- `MEMORY.md` — index one-liner updated to match.

**Immediate next-session behavior:**
1. **Do NOT lead with the VM daemon.** User deferred. Open `gm` normally and let user set the agenda.
2. A2b keeps accruing events via the hourly GH Actions scraper. No action needed.
3. `scripts/coverage_forecast.py` is available for a quick "are we on track for n=30 by 2026-09-30" arithmetic check — Second-Law safe, no interpretation.
4. Do NOT run `gate_report_a2b.py` — gate pre-committed to 2026-09-30 or n≥30.
5. If user brings up A3, use the deferred walkthrough from Session 6 conversation history — do not re-invent from scratch.

**Read these before doing anything:**
- `docs/PHASE_3_SESSION_3_LOG.md` — Session 6 log (this session).
- `docs/PHASE_3_SESSION_2_LOG.md` — Session 5 log (fetcher fix + backfill re-fire + daemon fix + Migration 010).
- `docs/PHASE_3_SESSION_1_LOG.md` — Session 4 log (fetcher-bug diagnosis).
- `docs/ROADMAP_V2.md` — current phase plan with adjustment triggers.
- `docs/preregistrations/README.md` and `KILL_COUNTER.md` — the discipline layer.
- `docs/METHOD.md` — confounds, gates, sign conventions.
- `docs/CHARTER.md` — kill criteria + scope.
- `docs/ORDERBOOK_DESIGN.md` — Phase 3e design + storage-volume math.
- Memory: `feedback_no_borrowing_from_siblings.md`, `feedback_no_premature_signals.md`, `feedback_gm_trigger.md`, `user_kepler_identity.md`, `reference_user_has_vm.md`. Non-negotiable.

**Prior state (as of 2026-08-03, Session 5 wrap):**

Phase: 3c LIVE + 3d LIVE (18 A2b labels in prod) + 3e READY FOR VM DEPLOY (Migration 010 applied, daemon fix live, seeder re-run). 304/304 tests. `main` at `456b12a`, pushed to origin+backup at the same SHA.

**Session 5 output (2026-08-03):** 6 commits.
- `a228be3` — candles.py two-phase fetcher (forward walk unchanged, then backward-fill on 1m skip-ahead). Fixes root cause of Session 4's A2b unlabelable-27. `_already_labeled` latent-bug also fixed (was checking `eq("0.3.0")` but stored rows are `0.3.0#h24`). Added `--retry-unlabelable` flag. 2 new regression tests. 300/300.
- `ef9aba3` — docs: A2b backfill re-fired live, **6 events × 3 horizons = 18 labeled rows**, 0 unlabelable, 2 stale_anchor. Split `{+1: 3, -1: 1, 0: 14}`. Not iterating (Second Law).
- `b60a525` — `scripts/seed_venue_coin_map.py` re-fired against prod: 250 rows, 247 `__ABSENT__` sentinels populated. capture_daemon now correctly skips venue-absent coins.
- `99d193c` — `capture_daemon` bug fix: was capping `--max-symbols` before applying `--venues` filter, so `--venues bitget --max-symbols 3` yielded 0 subs when top-3 entries were Bitget-absent. Extracted `_select_universe` pure helper (filter then cap). 4 new regression tests. 304/304. Re-smoke live confirmed 3 Bitget subs + acks.
- `b1342a4` — roadmap row for daemon fix.
- `456b12a` — Migration 010 applied to Supabase (comment-stripped variant — editor rejected the `--` line containing `|`). Three tables verified empty via smoke: `orderbook_snapshots_l2`, `orderbook_features`, `orderbook_universe`.

**Session 5 gh-auth drift caught pre-push again.** Active was `arbabfar`; recovered via `gh auth switch -u farhungers && gh auth setup-git`.

**Prior state (as of 2026-07-29, Session 4 wrap):**

Phase: 3c LIVE + 3d code-complete + 3e code-surface-complete + Migration 010 NOT YET APPLIED (blocked on user deploy-target decision). 298/298 tests. `main` at `c5de173`, pushed to origin+backup. Working tree clean.

**Session 4 output (2026-07-29):** 4 commits.
- `7c0cc6e` — candles.py spot-fallback shape bug fix (spot returns 8 cols vs perp 7; `_to_frame` now trims to 7). Also widened `.gitignore` to `data/events/**/*.jsonl` for venue subdirs.
- `67491f3` — A2b backfill fired live: 27/27 unlabelable with `anchor_before_first_walk_bar`. Verified via direct Bitget probe: retention is NOT the issue; root cause is that Bitget's 1m mix-candles endpoint returns the newest-200 bars within a wide `[startTime, endTime]` window instead of paging forward from `startTime`. Fix belongs in `src/defi_investor/candles.py::fetch_candles`. **Second Law: NOT touched this session.**
- `e9c28d5` — universe manager per-venue independence. Coins absent on a venue get `inst_id=None` (kept in universe if the other venue resolves) via `__ABSENT__:{coin}` sentinel in `venue_coin_map`. Capture_daemon filters None inst_ids. Seeder updated to write sentinel rows; NOT re-run against prod.
- `c5de173` — ROADMAP_V2 housekeeping (retention script done, absent-coin done, dedupe A3-gate).

**Memory updates this session (persisted, no commits):**
- `reference_user_has_vm.md` — VM specs question pinned. Next `gm` opens with it directly, before proposing A/B/C.
- `reference_github_tokens.md` — active-account drift observation logged. `gh auth switch` is machine-global; parallel-project switches to `arbabfar` cause 404 on push here. Fix: `gh auth status` before first push; if drifted, `gh auth switch -u farhungers && gh auth setup-git`.

**Session 3 output (2026-07-28), sorted by phase:**

_Phase 3a — library-first anchor:_ complete. `docs/library/` Zettelkasten (37 LIB entries) + `docs/preregistrations/` scaffold (FRAME_C1, HYPOTHESIS_A2a/A2b/A3, YAML_SCHEMA, KILL_COUNTER, REGISTRY, README).

_Phase 3b — ops foundation:_ complete. External cron via cron-job.org → GitHub Actions workflow_dispatch (Bitget cron unstuck from private-repo throttling). OSF integration: node `98kez` public, all pre-registration docs uploaded (`scripts/upload_prereg_to_osf.py`, idempotent by sha256). Git tags `prereg-A2a-v1`, `prereg-A2b-v1`, `prereg-A3-v1` on commit `8de07a3`, pushed to origin + backup.

_Phase 3c — multi-venue (LIVE):_ Migration 009 applied (composite PK `(venue, product_id)` + widened FKs on status_log and labels). `SupabaseWriter` composite-key aware. Binance Simple Earn parser + fetcher + scrape orchestrator + venue_coin_map shipped and running in `.github/workflows/scrape.yml` alongside Bitget. **422 Binance rows** in production Supabase alongside 455 Bitget rows. `venue_coin_map` seeded with 3 aliases (1000CHEEMS→CHEEMSUSDT etc.); 242 venue-absent coins identified.

_Phase 3d — v0.3.0 triple-barrier labeler (code-complete):_ `src/defi_investor/labelers/triple_barrier_v030.py` implements HYPOTHESIS_A2b exactly (barriers = anchor_close × exp(±k × sigma_20d), k=2.0 pre-committed, multi-horizon 24h/48h/168h returned per call). `scripts/backfill_labels_v030.py` writes 3 rows/event via labeler_version suffix trick (`0.3.0#h24` etc.). `src/defi_investor/backtest/family_wise.py` has Holm-Bonferroni (N_REGISTERED=3 tracks KILL_COUNTER.md). `scripts/gate_report_a2b.py` runs binomial test per horizon with Holm cascade. **Backfill not yet run** — 9 pending sold-out events (8 Bitget + 1 Binance) would produce ~27 label rows.

_Phase 3e — L2 order-book pipeline (code-surface-complete):_ `src/defi_investor/orderbook/{bitget_l2,binance_l2}.py` both live-verified (~10 snapshots/sec/symbol, auto-reconnect). `L2Snapshot` shared shape. `features.compute_depth_asymmetry_5min` per A3 spec (12 tests). `storage.BatchedL2Writer` (async, 500-row/2s batches, drop-oldest backpressure, error-resilient, 7 tests). `universe.build_universe` returns 541 coins with venue_coin_map overrides (10 tests including empty-`bitget_listings` fallback regression). `capture_daemon.py` runnable with `--venues`, `--max-symbols`, `--dry-run`. `scripts/backfill_labels_a3.py` + `scripts/gate_report_a3.py` complete. **Migration 010 NOT applied**, capture_daemon NOT deployed (blocked on user deploy-target decision A/B/C per `docs/ORDERBOOK_DESIGN.md`).

_Housekeeping this session:_ Control-arm bug fix in `scripts/gate_report.py` (dead-code KeyError + n<2 guard). BGBTC parser drift fix (added `OnChainElite` to `LIST_DATA_BIZLINES`). Identity renamed Vault→Kepler mid-session per user.

**Immediate next-session behavior:**
1. `gm` trigger routine — open with the VM specs question directly (per `memory/reference_user_has_vm.md`). If VM fits: use it. If not: A (local PC) / B (free-tier cloud, no Oracle) / C (paid VPS $4-6/mo). Once picked: apply Migration 010, start `capture_daemon`, re-run `scripts/seed_venue_coin_map.py` against prod to populate `__ABSENT__` rows.
2. Fix `fetch_candles` paging: probe first page, if `first_bar > startTime + tolerance`, issue bounded-window request with a moved `endTime` to force older data. Add a unit test with a fake Bitget response that reproduces skip-ahead. Re-run `scripts/backfill_labels_v030.py`; the 33 existing unlabelable rows overwrite via upsert. **Do NOT tune k, do NOT rerun before the fix.**
3. Before first push, run `gh auth status`; if active account isn't `farhungers`, run `gh auth switch -u farhungers && gh auth setup-git`.

**Read these before doing anything:**
- `docs/PHASE_3_SESSION_1_LOG.md` — this session's log (write it before closing).
- `docs/ROADMAP_V2.md` — current phase plan with adjustment triggers.
- `docs/PHASE_2_SESSION_2_LOG.md` — prior session (Phase 2 wrap).
- `docs/preregistrations/README.md` and `KILL_COUNTER.md` — the discipline layer.
- `docs/METHOD.md` — confounds, gates, sign conventions.
- `docs/CHARTER.md` — kill criteria + scope (updated 2026-07-28 for multi-venue).
- `docs/ORDERBOOK_DESIGN.md` — Phase 3e deploy options.
- Memory: `feedback_no_borrowing_from_siblings.md`, `feedback_no_premature_signals.md`, `feedback_gm_trigger.md`, `user_kepler_identity.md`. Non-negotiable.

Read in this order:
1. `README.md` — vision + hypothesis in plain language
2. `docs/CHARTER.md` — hypothesis, scope, kill criteria, phase gates
3. `docs/DATA_MODEL.md` — Bitget Earn product taxonomy, event schema, label design
4. `docs/METHOD.md` — confounds, statistical power, purged CV
5. `docs/SCRAPER.md` — data acquisition contract (what to build first)
6. `docs/LAB_CASE.md` — the LABUSDT motivating example
7. `docs/ROADMAP.md` — Phase 1 build plan for you

## Identity

Sign your work as **Kepler** when working on this project. `Argus` is mm-radar. `Polaris` is FAR. `Scrivener` is WriterProject. Kepler fits the discipline stack: patient data-fitting, discarding wrong models against a running kill counter, only accepting the hypothesis when the data forces it — same posture as METHOD.md and the pre-registration protocol.

Historical note: prior sessions signed as `Vault`. Renamed 2026-07-28 mid-Phase-3e because the user already had a "Vault" elsewhere. Git commits and docs authored before the rename retain the old signature; new work signs as Kepler.

## Discipline stack (de Prado *Advances in Financial Machine Learning*)

1. **Features before backtest.** No optimization loops on unlabeled data. Define the label schema, collect data, then measure.
2. **Second Law: do not research under the influence of a backtest.** If you see a preliminary result, do not iterate on it. Log it, walk away, come back next phase.
3. **Purged CV with embargo.** For any statistical claim on time-series labels, use `PurgedKFold` in `src/defi_investor/backtest/cv.py` (built from de Prado Ch 7).
4. **PSR / DSR gate** before declaring an edge. Implemented in `src/defi_investor/backtest/stats.py` (built from de Prado Ch 14 and Bailey & de Prado 2012).
5. **Corpus discipline.** Persist the event catalog to Supabase (new schema, not mm-radar's), not to ephemeral JSONL, so the corpus survives runner recycling.
6. **Kill criteria live in `CHARTER.md`.** If any is tripped, stop and report. Do not "just try one more feature."

## Rules of engagement (inherited from user)

- **No em-dashes anywhere in prose.** Ever. Top AI tell for this user.
- **Do not schedule the user's time.** No "tonight", "tomorrow", "this week". Describe work, not when.
- **One recommendation, not menus.** Reserve questions for irreversible decisions.
- **Do not prescribe user engagement.** No "close the laptop", "you're done", "walk away".
- **Maximum autonomy.** Default to doing, not asking. Only escalate on hard-NOs: user-only secrets, account creation, no credentials.
- **GitHub safety.** User's account was banned before. Never push binaries. Confirm before pushing anything. Assume user owns this repo under their `farhungers` GH handle unless told otherwise.
- **Perfectionist approach.** Pick the rigorous fix. Do not accept "decorative fake data" as a solution.

## What you must NOT do without explicit user approval

- Push to any git remote
- Take live positions (this is research, not trading)
- Scrape Bitget at aggressive rates (respect their rate limits, use user-agent identifying research)
- Create paid accounts or spend money
- Modify `mm-radar` or `FAR` files
- Skip the kill criteria in `CHARTER.md`

## Where things live

- `README.md` — vision
- `CHARTER.md` (in `docs/`) — investigation charter
- `docs/` — all research artifacts
- `data/events/` — event catalog JSONL (once scraper is built)
- `data/raw/` — raw Bitget API/scrape captures for provenance
- `src/` — code (does not exist yet, Phase 1)
- `.gitignore` — must exclude `data/raw/*` and any `.env`

## Handoff protocol

When you finish a phase, update:
1. `docs/CHARTER.md` "Current phase" line
2. This file's "Current state" section
3. Write a `docs/PHASE_N_LOG.md` with what you shipped, what surprised you, what the next AI needs to know

The user pastes conversation summaries into Supabase or into a followup session. Keep docs the source of truth, not chat history.

— Vault seeded this project; renamed to Kepler in Phase 3e per user request. Whoever picks it up next, keep the identity name.
