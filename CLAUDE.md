# CLAUDE.md — defi-investor project

You are working on **defi-investor**, a research project (not a production trading bot yet) investigating whether Bitget's Earn program parameters and lifecycle events are correlated with pump-and-dump behavior of the underlying token, and whether that correlation is exploitable.

## Origin

Sister project to `mm-radar` (at `C:\Users\farha\OneDrive\Desktop\shitcoindetector\mm-radar\`). A previous session there (as Argus) did the initial deep logic audit on this hypothesis. That audit concluded the concept did not belong inside mm-radar because clock, universe, and lifecycle mismatch. It belongs in its own repo. This is that repo.

**Do not touch mm-radar from this project.** Sibling. Different discipline stack.

## Current state (as of 2026-07-10, Phase 2 Session 1 close)

**Phase: 2 — infrastructure fully in place, pilot burning for labels.** Phase 1 scraper live on `*/15` GH Actions cron. Phase 2 labeling + confound + gate-report + dashboard pipeline shipped and green. 134/134 tests. 15 commits pushed to `github.com/farhungers/defi-investor` (private, `main` at `6ff1277`).

Component status:
- Scraper (Phase 1): LIVE. `earn_events` ≈399 rows, `earn_events_status_log` accumulating 2→6 transitions.
- Telegram alerts: LIVE. `@Defiinvestor_Bot` sends observation-only rich cards on new listings, sold-outs, re-opens, stalls, drift.
- Labeler (Phase 2): LIVE, nightly. `earn_event_labels` at 104 rows across 4 labeler versions. `LABELER_VERSION = "0.2.1"` current.
- Backtest primitives: BUILT FROM SCRATCH from de Prado Ch 7 (purged CV) + Ch 14 (PSR / HHI / uniqueness). No sibling reads.
- Gate report: `scripts/gate_report.py` runnable today, will print meaningful primary universe once first 7-day windows close (~2026-07-16 onward).

**Immediate next-session behavior:** WATCH, DO NOT TOUCH. Second Law per CHARTER §5. Real Phase 3 gate call is n ≥ 30 primary universe. Realistic ETA 2-4 weeks.

**Read these before doing anything:**
- `docs/PHASE_2_SESSION_1_LOG.md` — freshest handoff.
- `docs/PHASE_2_PLAN.md` — the plan.
- `docs/METHOD.md` — the discipline (confounds, gates, sign conventions).
- `docs/CHARTER.md` — kill criteria.
- Memory: `feedback_no_borrowing_from_siblings.md`, `feedback_no_premature_signals.md`. Non-negotiable.

**If genuinely impatient, order of value:**
1. Add OI snapshot step to the scraper cron (unlocks a real confound tag from now on).
2. Apply per-event uniqueness weights inside `gate_report.py`.
3. Wire a paid TOTAL3 data source.

Everything else past that is pilot patience.

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
