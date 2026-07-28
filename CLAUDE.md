# CLAUDE.md — defi-investor project

You are working on **defi-investor**, a research project (not a production trading bot yet) investigating whether Bitget's Earn program parameters and lifecycle events are correlated with pump-and-dump behavior of the underlying token, and whether that correlation is exploitable.

## Origin

Sister project to `mm-radar` (at `C:\Users\farha\OneDrive\Desktop\shitcoindetector\mm-radar\`). A previous session there (as Argus) did the initial deep logic audit on this hypothesis. That audit concluded the concept did not belong inside mm-radar because clock, universe, and lifecycle mismatch. It belongs in its own repo. This is that repo.

**Do not touch mm-radar from this project.** Sibling. Different discipline stack.

## Current state (as of 2026-07-28, Phase 3 Session wrap)

**Phase: 3c LIVE + 3d code-complete + 3e code-surface-complete.** 283/283 tests. `main` locally at `562e424`; last pushed to origin+backup at `cd917d8` — **8 commits ahead of remote** (all awaiting user push).

**Session 3 output (2026-07-28), sorted by phase:**

_Phase 3a — library-first anchor:_ complete. `docs/library/` Zettelkasten (37 LIB entries) + `docs/preregistrations/` scaffold (FRAME_C1, HYPOTHESIS_A2a/A2b/A3, YAML_SCHEMA, KILL_COUNTER, REGISTRY, README).

_Phase 3b — ops foundation:_ complete. External cron via cron-job.org → GitHub Actions workflow_dispatch (Bitget cron unstuck from private-repo throttling). OSF integration: node `98kez` public, all pre-registration docs uploaded (`scripts/upload_prereg_to_osf.py`, idempotent by sha256). Git tags `prereg-A2a-v1`, `prereg-A2b-v1`, `prereg-A3-v1` on commit `8de07a3`, pushed to origin + backup.

_Phase 3c — multi-venue (LIVE):_ Migration 009 applied (composite PK `(venue, product_id)` + widened FKs on status_log and labels). `SupabaseWriter` composite-key aware. Binance Simple Earn parser + fetcher + scrape orchestrator + venue_coin_map shipped and running in `.github/workflows/scrape.yml` alongside Bitget. **422 Binance rows** in production Supabase alongside 455 Bitget rows. `venue_coin_map` seeded with 3 aliases (1000CHEEMS→CHEEMSUSDT etc.); 242 venue-absent coins identified.

_Phase 3d — v0.3.0 triple-barrier labeler (code-complete):_ `src/defi_investor/labelers/triple_barrier_v030.py` implements HYPOTHESIS_A2b exactly (barriers = anchor_close × exp(±k × sigma_20d), k=2.0 pre-committed, multi-horizon 24h/48h/168h returned per call). `scripts/backfill_labels_v030.py` writes 3 rows/event via labeler_version suffix trick (`0.3.0#h24` etc.). `src/defi_investor/backtest/family_wise.py` has Holm-Bonferroni (N_REGISTERED=3 tracks KILL_COUNTER.md). `scripts/gate_report_a2b.py` runs binomial test per horizon with Holm cascade. **Backfill not yet run** — 9 pending sold-out events (8 Bitget + 1 Binance) would produce ~27 label rows.

_Phase 3e — L2 order-book pipeline (code-surface-complete):_ `src/defi_investor/orderbook/{bitget_l2,binance_l2}.py` both live-verified (~10 snapshots/sec/symbol, auto-reconnect). `L2Snapshot` shared shape. `features.compute_depth_asymmetry_5min` per A3 spec (12 tests). `storage.BatchedL2Writer` (async, 500-row/2s batches, drop-oldest backpressure, error-resilient, 7 tests). `universe.build_universe` returns 541 coins with venue_coin_map overrides (10 tests including empty-`bitget_listings` fallback regression). `capture_daemon.py` runnable with `--venues`, `--max-symbols`, `--dry-run`. `scripts/backfill_labels_a3.py` + `scripts/gate_report_a3.py` complete. **Migration 010 NOT applied**, capture_daemon NOT deployed (blocked on user deploy-target decision A/B/C per `docs/ORDERBOOK_DESIGN.md`).

_Housekeeping this session:_ Control-arm bug fix in `scripts/gate_report.py` (dead-code KeyError + n<2 guard). BGBTC parser drift fix (added `OnChainElite` to `LIST_DATA_BIZLINES`). Identity renamed Vault→Kepler mid-session per user.

**Immediate next-session behavior:** Three user decisions pending (all noted at end of every recent commit):
1. Push 8 commits to origin + backup.
2. Run `scripts/backfill_labels_v030.py` live (9 events × 3 horizons; idempotent).
3. Pick deploy target for `capture_daemon` (A local / B free cloud / C paid VPS $4-6/mo per `docs/ORDERBOOK_DESIGN.md`); then apply Migration 010 and start the daemon.

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
