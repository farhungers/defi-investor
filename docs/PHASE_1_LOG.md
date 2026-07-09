# PHASE_1_LOG — Vault's Phase 1 kickoff session

**Session date:** 2026-07-09
**Identity:** Vault (first Phase 1 session)
**Prior:** Phase 0 seeded by Argus.

## Shipped

- **Task 1: API probe (complete).** `docs/PHASE_1_PROBE_LOG.md`. REST API is user-account-only; Next.js SSR blob at `bitget.com/asia/earning` is the winning path.
- **Task 2: Data model (complete).** `src/defi_investor/models.py` with `EarnEvent` dataclass, provenance fields, apy/step helpers. `db/schema.sql` drafted, not yet applied to Supabase.
- **Task 3: Parser (complete).** `src/defi_investor/parsers/next_data.py`. Extracts `__NEXT_DATA__`, iterates `listData` + `hotData`, dedupes by product_id, tags schema drift.
- **Task 4: End-to-end scraper (complete).** `src/defi_investor/scraper.py`. Fetch → atomic raw write → parse → merge with existing catalog → JSONL write. Verified against live Bitget (2 sequential runs).

## Verified live behavior

- **399 products** captured on 2026-07-09 18:52 UTC scrape
- **LAB present**: product_id `1438002720001814528`, APR 365%, `sold_out=true`, start_time 2026-05-12
- **18 pools at APR ≥ 50%**: 15 in the `Savings` family, 3 sold-out (LAB, SKYAI, SXT)
- **Dedupe works**: second scrape produces 0 new, 399 updated, 0 status transitions
- **Provenance intact**: every row carries `raw_capture_sha256`, `raw_capture_path`, `scraper_version`

## Tests

27 tests, all passing. Fixture-based parser tests use a canned 2026-07-09 HTML capture. Full scraper flow tested offline via `monkeypatch` on `fetch_earning_html`. No network in the test suite.

## What surprised me

1. **Taxonomy mismatch with CHARTER.** CHARTER pre-committed to six product families (PoolX, Simple Earn Flexible, Simple Earn Fixed, Shark Fin, Dual Investment, On-chain Earn). Reality has different labels: `Savings` (dominates), `PosStaking`, `SharkFin`, `CashPlus`, `FundMarket`, `Trend`. LAB is `Savings`, not what Argus called "PoolX" in prior planning. **DATA_MODEL.md updated** with a note pointing to the probe log for the corrected mapping. Original narrative retained as reasoning, but implementation uses wire labels.

2. **"PoolX" is not on the Earn landing page.** It lives at `/earning/launchpool` which is client-rendered (no SSR JSON). If Phase 2 wants it, it's a separate scraper. Not urgent since the LAB-shaped hypothesis is fully addressable via `Savings`.

3. **365% APR is a template, not per-token.** Three separate coins (LAB, OGN, GWEI) sit at exactly 365%. This means Bitget uses that number as a boilerplate tier for a subset of new-listing Savings pools. Interesting hypothesis refinement: the "365%-tier" pool is a distinct SKU worth cohorting separately.

4. **Pool total size is NOT in the SSR blob.** `apyList[0].maxStepValue` (1000 LAB for LAB) is the **per-user cap**, not the total pool size. Getting total pool requires the product detail page. Deferred; hypothesis-testable properties are still present without it (APR, start_time, sold_out status, transitions).

5. **`sold_out_ts` precision is scrape-cadence-limited.** We record "first scrape where status = 6" and tag precision accordingly. If a pool sells out between two scrapes, we lose sub-cadence precision. At 15-minute cadence this is acceptable for a distribution-level hypothesis.

## What did NOT ship (out of scope for this session)

- **Task 5: Supabase integration.** Needs user to provision a new Supabase project (or a separate schema in an existing one) and hand over `SUPABASE_URL` + `SUPABASE_SERVICE_ROLE_KEY`. Then apply `db/schema.sql`. Then extend `scraper.py` with a `supabase_upsert` function. All doable, but blocked on user credentials.
- **Task 6: Scheduler.** Needs user to pick GH Actions vs OCI VM vs Supabase Edge Fn. Recommend OCI VM (cheap, user has tenancy). GH Actions works but raw captures accumulate in repo.
- **Task 7-9: Uptime monitoring, PosStaking parser, completion report.** Follow after 5+6.
- **Product detail page probe.** For total pool size. Cheap follow-up if user cares about H1 sub-hypothesis power.

## Immediate next actions the next Vault session should take

1. Ask user to greenlight Supabase provisioning (or park file-only for 30 days as a pilot).
2. Pick scheduler. Recommend OCI VM if the user is comfortable with a small ARM instance. Otherwise GH Actions.
3. Ship `supabase_upsert` in the scraper.
4. Turn the cron on.

## State handoff to next session

- Repo state: 27/27 tests green. Working tree clean. No git init yet (user should decide if this repo is public/private and where).
- Current on-disk catalog: `data/events/2026-07.jsonl` with 399 events. Not committed, not backed up. Delete before first "real" run or preserve as pilot baseline.
- Raw captures: `data/raw/2026-07-09/*.html` — three files from probe + two scraper runs.
- No secrets in the repo.

— Vault, signing off Phase 1 Session 1
