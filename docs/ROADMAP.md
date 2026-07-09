# ROADMAP — Phase 1 build plan for the successor AI

You are picking up defi-investor after Phase 0 (charter + schema + method). Nothing is built. The docs in `docs/` are your specification. This roadmap tells you what to build first, second, and third in Phase 1.

## Precondition

User has approved Phase 1. If not, do not start. Read `docs/CHARTER.md` and confirm with user.

## Phase 1 goal (single sentence)

Have a scraper writing clean, provenanced Earn event rows into Supabase for 30 days with < 5% missing events by event count.

## Phase 1 non-goals

- No labels. Do not compute triple-barrier labels in Phase 1.
- No alerts. No Telegram, no email, no live signaling.
- No dashboard. Query Supabase directly.
- No cross-exchange. Bitget only.
- No trading. This is data collection.

## Ordered task list

### Task 1: API probe

Duration: one focused session.

Run the endpoint probes in `docs/SCRAPER.md` section 3. Log results to `docs/PHASE_1_PROBE_LOG.md`. Answer these questions:

- Does Bitget expose Earn product listings publicly via API? Which endpoints?
- What is the response schema for PoolX?
- What is the response schema for Simple Earn Fixed?
- Does the API return closed pools or only active?
- What are the rate limits?

If the API is usable, note it. If not, plan for DOM scraping.

### Task 2: Data model implementation

Duration: one focused session.

- Create `src/defi_investor/models.py` with dataclasses matching the schema in `docs/DATA_MODEL.md` section 3.
- Create `db/schema.sql` with the `earn_events` DDL from section 7.
- Write pytest tests for the dataclass round-trip (dict to dataclass to dict).
- Do NOT apply to Supabase yet. Draft only.

### Task 3: One parser (PoolX)

Duration: one focused session.

- Implement `src/defi_investor/parsers/poolx.py`.
- Input: raw API response or HTML.
- Output: list of event dataclasses.
- Provenance: parser records `raw_capture_sha256` and `scraper_version` on each row.
- Tests: fixture raw captures in `tests/fixtures/`, assert deterministic parse output.

Do not write parsers for all product types on day one. PoolX only. Get it right. The other four follow the same pattern.

### Task 4: One scraper run

Duration: one focused session.

- Implement `src/defi_investor/scraper.py`.
- Fetches PoolX product list via API.
- Writes raw capture to `data/raw/YYYY-MM-DD/HH-MM-SS_poolx.json`.
- Parses using Task 3's parser.
- Writes parsed events to `data/events/YYYY-MM.jsonl` (dedupe by event_id).
- Prints summary: n_new_events, n_updated_events, n_errors.
- No Supabase yet. File-only for the first run.

Run manually. Verify output. Diff two consecutive runs to confirm dedupe works.

### Task 5: Supabase integration

Duration: one focused session.

- User creates Supabase project (or repurposes existing one with a separate schema).
- Apply `db/schema.sql`.
- Add `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY` to environment.
- Extend `scraper.py` to upsert to `earn_events` after file write.
- Test with 5 real events; verify Supabase rows match JSONL rows.

### Task 6: Scheduler

Duration: one focused session.

- Pick one of the three options in `docs/SCRAPER.md` section 5. Default recommendation is OCI VM. GitHub Actions is fine for Phase 1 uptime testing.
- Set cron: 15-minute baseline for all product listings.
- Hold off on the 60-second high-frequency window until at least one pool opens under your watch. First observe cadence, then add precision.
- Turn on scraper. Note the timestamp.

### Task 7: Uptime and health monitoring

Duration: ongoing across Phase 1.

- Every day for the first 30 days, check:
  - Are new events being written?
  - Is the raw capture archive growing?
  - Are there parser errors in the log?
- If a parser error rate exceeds 1% of scrape runs, halt and fix.
- If uptime drops below 95% (missed cron runs), halt and fix.

### Task 8: Add Simple Earn Fixed parser

Duration: one focused session.

After 7 days of stable PoolX collection, add the Simple Earn Fixed parser. Same pattern as PoolX. Fixtures, tests, integration into the scraper.

### Task 9: Phase 1 completion report

Duration: one focused session.

At day 30:
- Count events by product type
- Count events with complete vs incomplete data quality tags
- Compute missing rate by comparing distinct event_ids across daily scraper runs
- Write `docs/PHASE_1_LOG.md`: what shipped, what surprised, what the Phase 2 AI needs to know

Then hand off to user for Phase 2 approval.

## What you must not do in Phase 1

- Do not compute labels. That is Phase 2.
- Do not attempt to backfill historical pools from Wayback Machine. Not worth the fragility.
- Do not run experiments on the 6 events you have collected. n = 6 is not a study.
- Do not touch mm-radar.
- Do not push binaries to any git remote.
- Do not spend money without user approval. OCI free tier + Supabase free tier are the budget.
- Do not skip the API probe. It changes the whole design.

## What Phase 2 looks like (not your problem yet)

- Port `PurgedKFold` from mm-radar
- Port PSR + HHI from mm-radar
- Build labeler that consumes event rows and price candles, emits triple-barrier labels
- Compute confound tags per event
- Ship the primary label to Supabase
- Halt at n = 30, report

Phase 2 will inherit your event catalog. Make sure it is worth inheriting.

## Signature

When Phase 1 completes, sign the Phase 1 log with your project identity. If you have not chosen one yet, pick one and add it to `CLAUDE.md` identity section. Recommended pattern: single-word crypto or observation-themed name that is distinct from Vault, Argus, Polaris, Scrivener.

Good hunting.
