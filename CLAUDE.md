# CLAUDE.md — defi-investor project

You are working on **defi-investor**, a research project (not a production trading bot yet) investigating whether Bitget's Earn program parameters and lifecycle events are correlated with pump-and-dump behavior of the underlying token, and whether that correlation is exploitable.

## Origin

Sister project to `mm-radar` (at `C:\Users\farha\OneDrive\Desktop\shitcoindetector\mm-radar\`). A previous session there (as Argus) did the initial deep logic audit on this hypothesis. That audit concluded the concept did not belong inside mm-radar because clock, universe, and lifecycle mismatch. It belongs in its own repo. This is that repo.

**Do not touch mm-radar from this project.** Sibling. Different discipline stack.

## Current state (as of 2026-08-03, Session 5 mid)

**Phase: 3c LIVE + 3d LIVE (A2b labels landed) + 3e READY FOR VM DEPLOY (Migration 010 applied, daemon proven live).** 304/304 tests. `main` pushed through `b1342a4` to origin+backup; Migration 010 doc bump pending commit.

**Session 5 output (2026-08-03) so far:** 1 commit + docs.
- `a228be3` — candles.py two-phase fetcher (forward walk unchanged, then backward-fill on skip-ahead), fixes root cause of 2026-07-29 A2b unlabelable-27. `_already_labeled` latent-bug also fixed (was checking `eq("0.3.0")` but rows are `0.3.0#h24`). Added `--retry-unlabelable` flag. 2 new regression tests. 300/300.
- A2b backfill re-fired live: **6 labeled events × 3 horizons = 18 labeled rows**, 0 unlabelable, 0 skipped, 2 stale_anchor. Split `{+1: 3, -1: 1, 0: 14}`. Not iterating on this split (Second Law).
- VM specs confirmed with user: Linux, Py 3.11+, always-on, RAM OK, disk under 2GB but daemon writes to Supabase not local so that's fine. VM is the deploy target for capture_daemon.

**Blocking on user for the rest of Session 5:**
1. Migration 010 paste into Supabase SQL editor (contents: `db/migrations/010_orderbook.sql`). No direct psql path in `.env` — same manual workflow as Migration 009.
2. Push confirmation (unpushed commit `a228be3`).

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
