# PHASE_1_SESSION_2_LOG — Vault's Phase 1 Session 2

**Session date:** 2026-07-10
**Identity:** Vault (Phase 1 Session 2)
**Prior:** Session 1 shipped Tasks 1-4 (probe, model, parser, file-only scraper). See `PHASE_1_LOG.md`.

## Shipped

- **Task 5 code path (B1) — the offline half.** Everything the scraper needs to write to Supabase is in place. The last mile (schema apply + live smoke test) is blocked on user creds.
  - `src/defi_investor/db.py`: `Writer` protocol, `NoOpWriter`, `SupabaseWriter` (batches upserts on `earn_events` with `on_conflict=product_id`, appends to `earn_events_status_log`), `build_writer()` env-var factory.
  - `src/defi_investor/scraper.py`: `run_scrape()` now takes an optional `writer` param; defaults to `build_writer()`. `ScrapeResult` gained `events_upserted_remote` + `transitions_logged_remote`. `main()` calls `dotenv.load_dotenv()` if available.
  - `pyproject.toml`: added `supabase>=2.5` and `python-dotenv>=1.0`.
  - `.env.example`: documents `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`.
- **Tests.** 38/38 green (was 27; +10 db tests, +1 injected-writer scraper test). Covers batching, on_conflict shape, empty-input no-ops, NoOp fallback, env-var driven factory, and full offline flow mirroring the merged catalog to a recording writer.

## Design choices worth remembering

- **NoOpWriter is intentional, not a stub.** Missing creds must not crash the scraper — file mode is the corpus of record; Supabase is a mirror. `build_writer()` logs the fallback so cron doesn't silently degrade.
- **`Writer` client is injectable.** The supabase package is only imported inside `SupabaseWriter.__init__` when no client is passed. Tests run without the dep loaded. Helps if Bitget scraper ever runs somewhere without the supabase Python SDK.
- **Batch size 500.** Below Supabase's default row-limit per request and well above the ~400-event working set. One HTTP call per scrape covers the current corpus.
- **`upsert_events` writes the full merged catalog every scrape**, not just deltas. Keeps `last_seen_at` accurate for every product without a separate touch step. Cost is one batched upsert of ~400 rows every 15 min = trivial.

## What did NOT ship (blocked on user)

- **Applying `db/schema.sql` to a real Supabase project.** Needs the URL + `service_role` key so I can hand the user the exact SQL to paste (or use the CLI if they prefer).
- **Live smoke test.** After schema is applied, run one scrape against real Supabase, verify 399 rows in `earn_events` with LAB present, and confirm status_log stays empty on first scrape.
- **Scheduler wiring (B2).** Blocked on user picking OCI VM vs GH Actions vs Edge Fn per `PHASE_1_EXECUTION_PLAN.md` §A2.

## Handoff — what the user needs to paste next

Per `PHASE_1_EXECUTION_PLAN.md` §D:

```
Supabase URL: <paste>
Supabase service_role key: <paste>
Scheduler choice: [OCI / GH Actions / Edge Fn]
Retention policy: [30-day rolling / Backblaze / local forever]
Repo home: [private GH / public GH / stay local]
```

Once creds are in, next session:
1. Copy the two vars into `.env` (gitignored).
2. Paste `db/schema.sql` into Supabase SQL editor. Confirm both tables created.
3. Run `python -m defi_investor.scraper` once. Verify Supabase gets ~399 rows and `events_upserted_remote` in the JSON output equals `events_seen`.
4. Then start B2 wiring.

## State handoff to next session

- Repo state: 38/38 tests green. No git init still. `.env.example` present; `.env` not created.
- On-disk catalog: unchanged from Session 1 (`data/events/2026-07.jsonl` from the earlier live-verify runs).
- Raw captures: unchanged.
- No secrets in the repo.

— Vault, signing off Phase 1 Session 2
