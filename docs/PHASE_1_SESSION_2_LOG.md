# PHASE_1_SESSION_2_LOG — Vault's Phase 1 Session 2

**Session date:** 2026-07-10
**Identity:** Vault (Phase 1 Session 2)
**Prior:** Session 1 shipped Tasks 1-4 (probe, model, parser, file-only scraper). See `PHASE_1_LOG.md`.

## Shipped

**Task 5 (Supabase integration) — done end-to-end and live.**
- `src/defi_investor/db.py`: `Writer` protocol, `NoOpWriter`, `SupabaseWriter` (batched upserts on `earn_events` with `on_conflict=product_id`, appends to `earn_events_status_log`, paginated `fetch_events()` for state hydration).
- `src/defi_investor/scraper.py`: `run_scrape()` mirrors merged catalog to writer, rehydrates prior state from writer when local JSONL is missing (Actions).
- `db/schema.sql` applied to Supabase. First live scrape: 399 rows, LAB present with correct fields, 7 status transitions logged.

**Task 8 (product detail probe) — done, list-only path confirmed viable.**
- Findings in `docs/PHASE_1_PROBE_LOG_v2.md`.
- Product-detail URLs 404 across all guessed patterns; Bitget renders details as client-side modal, no SSR to scrape.
- Total pool size not publicly exposed anywhere — kill-clause §B4 applies, H3 still testable list-only.
- **Per-tier APR ladder IS in the main list page** and was being discarded. Migration shipped (see below).

**Tier migration (v0.2.0) — applied live.**
- `db/migrations/002_add_tiers.sql`: `ADD COLUMN tiers JSONB NOT NULL DEFAULT '[]'::jsonb` + partial index on multi-tier rows.
- Parser preserves full `apyList` verbatim.
- Verified live: LAB 1-tier, USDT 2-tier (1.88% first 300k, 1.06% next 50M), PAXG 2-tier (99.99% first 0.025, 2% next 125), PEPE 2-tier, ARB/USDGO 3-tier. Distribution: 359×1-tier, 30×0-tier (likely empty apyList = sold-out), 8×2-tier, 2×3-tier.
- SCRAPER_VERSION bumped to 0.2.0.

**Task 6 (scheduler) — Option B GH Actions live.**
- `.github/workflows/scrape.yml`: `*/15 * * * *` cron + `workflow_dispatch`. Concurrency guard, Python 3.12 with pip cache, 5-min timeout.
- Supabase creds set as repo secrets via `gh secret set`.
- First manual run (id 29057108742): 20s, hydrated 399 prior rows from Supabase, upserted 399, artifacts uploaded (raw HTML 30-day retention, catalog snapshot 7-day retention).
- Pilot clock is running.

**Repo pushed to GitHub.**
- `https://github.com/farhungers/defi-investor` (private).
- `arbabfar` → `farhungers` handle corrected everywhere (CLAUDE.md, execution plan, memory).
- Local git identity uses noreply email `301908416+farhungers@users.noreply.github.com` so future commits attribute to profile.
- `deploy/` tree written but not deployed (OCI VM path deferred; GH Actions won instead).

**Tests.** 46/46 green (was 27 at end of Session 1). +10 db tests, +5 model tests (tiers), +4 parser tests (multi-tier), covered fetch_events pagination + tier preservation across round-trips.

## What did NOT ship this session

- **B3 Task 7 monitoring/alerting.** Scaffold pending. 48h burn-in must accumulate first per plan §B3. Recommend: build `scripts/uptime_check.py` in the next session, wire a nightly GH Actions workflow that fails loudly when the last scrape is > 30 min stale or when parser data_quality != 'complete'. GitHub emails farhungers on workflow failure — no Telegram bot needed for pilot alerting.
- **B5 Task 9 completion report.** Blocked on 30 continuous days of B2 uptime.
- **Backfill of pre-migration rows with tiers.** Not needed — every scrape re-upserts every row, so `tiers` populates naturally within one cron tick after migration.
- **OCI VM setup.** deploy/ tree lives in the repo for later; not deployed. Option B chosen instead.

## Design choices worth remembering

- **NoOpWriter is a first-class writer, not a stub.** `build_writer()` returns it when creds are unset. Scraper stays file-only in dev/CI without any code branching.
- **`Writer.fetch_events()` is the state hydration hook.** Local JSONL is the default source; Supabase is the fallback for ephemeral runners. This is why GH Actions runs don't corrupt `first_seen_at`.
- **`tiers` stored raw**, keeping Bitget's camelCase + string numerics (`apy`, `maxStepValue`, `minStepValue`, `productId`, `rateLevel`). Zero information loss; Phase 2 code coerces types when querying.
- **Batch size 500 for upserts, page size 1000 for fetch.** Both well below Supabase defaults, one call per scrape.
- **Artifact retention 30/7 days** matches Phase 1 §A3 default (30-day rolling). If we want longer, swap artifact retention or add Backblaze.

## State handoff to next session

- Repo state: 46/46 tests green. Two branches of interest: `main` (protected? no) at commit `8ee97d2`. `.env` in place locally (gitignored).
- Supabase live at `https://ewcalrgayfpwpcoielrl.supabase.co`. 399 rows in `earn_events` with tiers populated. `earn_events_status_log` accumulating.
- GH Actions cron running every 15 min. Watch: `https://github.com/farhungers/defi-investor/actions`.
- Local Windows catalog in `data/events/2026-07.jsonl` — historical, not the source of truth anymore.

## Immediate next actions

1. Let the pilot burn for 48h. Watch Actions success rate and Supabase `last_seen_at` freshness.
2. Build `scripts/uptime_check.py` + `.github/workflows/uptime.yml` (nightly). Alert on: cadence gap > 30 min, any row with `data_quality != 'complete'`, coverage deviation > 10%.
3. After 7 days: sanity-check the tier distribution hasn't drifted and no sold-out event was missed by cadence.
4. After 30 days: write PHASE_1_COMPLETION.md, open Phase 2.

— Vault, signing off Phase 1 Session 2
