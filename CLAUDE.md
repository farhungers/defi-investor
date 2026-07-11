# CLAUDE.md — defi-investor project

You are working on **defi-investor**, a research project (not a production trading bot yet) investigating whether Bitget's Earn program parameters and lifecycle events are correlated with pump-and-dump behavior of the underlying token, and whether that correlation is exploitable.

## Origin

Sister project to `mm-radar` (at `C:\Users\farha\OneDrive\Desktop\shitcoindetector\mm-radar\`). A previous session there (as Argus) did the initial deep logic audit on this hypothesis. That audit concluded the concept did not belong inside mm-radar because clock, universe, and lifecycle mismatch. It belongs in its own repo. This is that repo.

**Do not touch mm-radar from this project.** Sibling. Different discipline stack.

## Current state (as of 2026-07-11, Phase 2 Session 2 wrap)

**Phase: 2 — infrastructure complete. All METHOD §1 confound slots instrumented. Pilot burning for labels.** 208/208 tests. `main` at `f4b0020` on `github.com/farhungers/defi-investor`. Working tree clean.

Component status:
- Scraper (Phase 1): LIVE on `*/15`. `earn_events` ≈399 rows, `earn_events_status_log` accumulating 2→6 transitions.
- Telegram alerts: LIVE. `@Defiinvestor_Bot` sends observation-only rich cards on new listings, sold-outs, re-opens, stalls, drift.
- Labeler (Phase 2): LIVE, nightly at 04:00 UTC. `earn_event_labels` at 104 rows across 4 labeler versions. `LABELER_VERSION = "0.2.1"` current.
- OI snapshots (§1.3): LIVE, `*/15` cadence. Migration 005 applied. `earn_oi_snapshots` populating.
- Vest unlocks (§1.2): LIVE, hourly-aligned. Migration 006 applied. `earn_next_unlocks` from tokenomist.ai SSR. 5-10% coverage expected.
- Control-arm (§1.4): LIVE, daily 03:00 UTC. Migration 007 applied. `bitget_listings` from `/spot/public/symbols`. DiD analysis deferred to Phase 3.
- Regime confound (§1.6): LIVE. Migration 008 applied. `btc_30d_realized_vol` + `btc_ret_30d_prior` on `earn_event_labels`; gate report split replaced with proper regime binary.
- Backtest primitives: BUILT FROM SCRATCH from de Prado Ch 7 (purged CV) + Ch 14 (PSR / HHI / uniqueness). `psr()` accepts float n; gate reads effective-n PSR after uniqueness deflation.
- Gate report: `scripts/gate_report.py` runnable today. Primary-universe rollup meaningful once first 7-day windows close (~2026-07-16 onward).
- Research library: `resaerchBOOKS/` (gitignored) holds AFML + MLAM PDFs; `docs/REFERENCES.md` maps sections to implemented vs queued work.

**Immediate next-session behavior:** WATCH, DO NOT TOUCH. Second Law per CHARTER §5. Real Phase 3 gate call is n ≥ 30 primary universe. Realistic ETA 2-4 weeks from 2026-07-11.

**Read these before doing anything:**
- `docs/PHASE_2_SESSION_2_LOG.md` — freshest handoff (five addenda covering OI, uniqueness-weighted PSR, vest, control-arm, regime).
- `docs/REFERENCES.md` — book stack and phase mapping.
- `docs/PHASE_2_SESSION_1_LOG.md` — prior session.
- `docs/PHASE_2_PLAN.md` — the plan.
- `docs/METHOD.md` — the discipline (confounds, gates, sign conventions).
- `docs/CHARTER.md` — kill criteria.
- Memory: `feedback_no_borrowing_from_siblings.md`, `feedback_no_premature_signals.md`. Non-negotiable.

**Only remaining unblocked build items are money-blocked:**
1. Paid TOTAL3 data source (CoinGecko Pro / CMC).
2. Paid vest data source (CryptoRank Business / DefiLlama Pro).

Everything else is calendar-bound or deferred to Phase 3 research.

Read in this order:
1. `README.md` — vision + hypothesis in plain language
2. `docs/CHARTER.md` — hypothesis, scope, kill criteria, phase gates
3. `docs/DATA_MODEL.md` — Bitget Earn product taxonomy, event schema, label design
4. `docs/METHOD.md` — confounds, statistical power, purged CV
5. `docs/SCRAPER.md` — data acquisition contract (what to build first)
6. `docs/LAB_CASE.md` — the LABUSDT motivating example
7. `docs/ROADMAP.md` — Phase 1 build plan for you

## Identity

Sign your work as **Vault** when working on this project. `Argus` is mm-radar. `Polaris` is FAR. `Scrivener` is WriterProject. Give this project its own name so the user can tell you apart across projects.

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

— Vault seeds this project. Whoever picks it up next, keep the identity name.
