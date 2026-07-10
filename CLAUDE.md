# CLAUDE.md — defi-investor project

You are working on **defi-investor**, a research project (not a production trading bot yet) investigating whether Bitget's Earn program parameters and lifecycle events are correlated with pump-and-dump behavior of the underlying token, and whether that correlation is exploitable.

## Origin

Sister project to `mm-radar` (at `C:\Users\farha\OneDrive\Desktop\shitcoindetector\mm-radar\`). A previous session there (as Argus) did the initial deep logic audit on this hypothesis. That audit concluded the concept did not belong inside mm-radar because clock, universe, and lifecycle mismatch. It belongs in its own repo. This is that repo.

**Do not touch mm-radar from this project.** Sibling. Different discipline stack.

## Current state (as of 2026-07-10, end of Vault Session 2)

**Phase: 1 — Tasks 1-6 + 8 shipped. 30-day pilot burning.** Scraper is live in GitHub Actions on `*/15` cron writing to Supabase. Tier ladder (`apyList`) preserved as JSONB. 46/46 tests green. Repo pushed private to `github.com/farhungers/defi-investor`.

Component status:
- Task 5 Supabase: LIVE. 399 rows in `earn_events`, LAB present, status log accumulating.
- Task 6 scheduler: GH Actions (Option B), `.github/workflows/scrape.yml`. First run at 2026-07-09 23:20 UTC hydrated 399 prior rows from Supabase, upserted 399, artifacts uploaded.
- Task 8 detail probe: DONE, list-only path confirmed viable. Detail URLs 404, pool size not public. Tier ladder was hidden in list SSR and is now captured (schema v0.2.0).

**Immediate blockers:** 48h uptime accumulation before B3 (monitoring). Nothing to ship right now that isn't gated on real pilot data.

**Next tasks:**
1. Build `scripts/uptime_check.py` + `.github/workflows/uptime.yml`. Alert channel = GH's default email on failed workflow (no Telegram bot needed for pilot).
2. Watch Actions success rate and Supabase `last_seen_at` freshness for 48h.
3. After 30 days: `docs/PHASE_1_COMPLETION.md`, open Phase 2.

See `docs/PHASE_1_LOG.md` (Session 1), `docs/PHASE_1_SESSION_2_LOG.md` (Session 2), and `docs/PHASE_1_EXECUTION_PLAN.md` (master plan).

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
