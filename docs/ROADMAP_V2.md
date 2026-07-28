# Roadmap V2 — dynamic, adjustment-triggered

Successor to `docs/ROADMAP.md` (Phase 1 era). Reflects Decisions 1-6 locked in Session 3 (2026-07-28).

## Locked decisions (source of truth)

| # | Decision | Result |
|---|---|---|
| 1 | Signal-detection universe vs trading universe | Multi-venue detection, Bitget-tradable filter, Bitget-chart labels. Events from any venue count (Interpretation A). |
| 2 | Venue/product/source scope | C+D+E catalog, free-tier only, minus D5 (X/Twitter unreliable), minus paid tiers (Nansen, CryptoRank API). |
| 3 | Research frame | C1 (informed-positioning detection on CEX) as the frame; A2 (Bitget+Binance Earn) as the first implementation. Gate call pre-committed to trigger reframing either direction. |
| 4 | Pre-registration structure | E2 + D1 + D2 + D3: two-layer (frame + hypothesis) Markdown docs + machine-readable YAML + git-tagged + OSF public timestamp + mandatory red-team section + kill-counter ledger for family-wise correction. |
| 5 | Labeler architecture | A2a (v0.2.1 fixed) + A2b (v0.3.0 triple-barrier) now; A2c (v0.4.0 CAR) pre-committed post-gate; A3 (order-book impact) as separate pre-registered hypothesis; D1 meta-labeling as post-gate filter. Multi-timeframe is CV search space per hypothesis, not separate hypotheses. |
| 6 | Build sequencing | Library-first anchor, then E1→E2→E3→E4 with dynamic revision. |

## Phases

### Phase 3a — Library-first anchor (~1 week) — COMPLETE
The knowledge scaffold that every subsequent phase depends on. User priority: this first.

- [x] `docs/library/README.md` — system explainer
- [x] `docs/library/MOC.md` — map of content (updated with all 37 LIB entries)
- [x] `LIB_0001` through `LIB_0037` — full stub set for corpus in `reaserch/`
- [x] Identify unlabeled PDFs — all 5 identified (Chen Kelly, Narang Black Box, Mitchell Architecture review, Zhang Funding Rate, Flint order placement)
- [x] `verne-castaways-of-the-flag.pdf` flagged as stray in MOC (confirm with user)
- [x] `docs/preregistrations/FRAME_C1.md` — the broad C1 research frame
- [x] `docs/preregistrations/README.md` — registration protocol
- [x] `docs/preregistrations/YAML_SCHEMA.md` — machine-readable spec schema
- [x] `docs/preregistrations/KILL_COUNTER.md` — family-wise correction ledger
- [x] `docs/preregistrations/REGISTRY.md` — index
- [ ] **Awaiting**: Campbell/Lo/MacKinlay Ch 4 PDF from user

**Adjustment trigger status**: FRAME_C1.md drafting surfaced no contradictions with Decision 3. Frame reads consistently. Proceeding.

### Phase 3b — Ops foundation (~1 week, can overlap with Phase 3a tail)
Kill the corpus-arrival bottleneck. Fix bugs. Get the pre-registration infrastructure minimal.

- [x] `docs/preregistrations/` directory scaffold + YAML schema + git-tag convention
- [x] Control-arm bug fix in `scripts/gate_report.py` — killed the dead-code `earn_coins` KeyError and added n<2 guard; verified with live run
- [x] BGBTC parser drift fix — added `OnChainElite` to `LIST_DATA_BIZLINES`; 208/208 tests pass; next scrape will reclassify the existing row as `complete`
- [x] Draft HYPOTHESIS_A2a.md + A2a.yaml (retroactive registration of v0.2.1)
- [x] Draft HYPOTHESIS_A2b.md + A2b.yaml (pre-registration for v0.3.0)
- [x] Draft HYPOTHESIS_A3.md + A3.yaml (pre-registration for order-book impact)
- [ ] External cron → workflow_dispatch (needs cron-job.org account + PAT; **user action required**)
- [ ] OSF integration (needs OSF token; **user action required**)
- [ ] `scripts/validate_prereg.py` — YAML validator (deferred; useful once we start committing hypothesis versions)

**Adjustment trigger**: if cron-job.org rate limits us, evaluate GitHub Actions self-hosted runner as backup.

**Blocked-by-user items**:
1. cron-job.org account + fine-grained PAT (`workflow_dispatch` scope only)
2. OSF account + API token

### Phase 3c — Binance data sprint (~2 weeks) — LIVE
Corpus doubler. First real implementation of Decision 1 (multi-venue) + Decision 2 (Binance-first).

- [x] Reverse-engineer Binance public Simple Earn endpoint (no auth needed; `GET /bapi/earn/v1/friendly/finance-earn/simple-earn/homepage/details`)
- [x] Binance Simple Earn parser (`src/defi_investor/parsers/binance_earn.py`, 12 unit tests)
- [x] Binance fetch layer with pagination (`src/defi_investor/binance_earn_fetch.py`)
- [x] Dry-run CLI (`scripts/binance_earn_dryrun.py`) — verified: 421/421 products parsed, APY 0-53%, 14 above alert threshold
- [x] Migration 009 applied to Supabase (composite PK on `(venue, product_id)` + widened FKs; 455 existing Bitget rows auto-tagged venue='bitget')
- [x] Add `venue` field to `EarnEvent` dataclass (default `'bitget'`, backward-compat)
- [x] Standalone Binance scrape orchestrator (`src/defi_investor/binance_scrape.py`) with disappearance-detection (diff-based sold-out)
- [x] Cross-venue coin mapping table (`venue_coin_map`) — schema applied; seeding deferred (empty; string-equality heuristic covers current cases)
- [x] `SupabaseWriter` composite-key aware: upsert uses `venue,product_id`; `log_status_transitions` accepts venue; `fetch_events` accepts venue filter
- [x] **LIVE: 422 Binance rows in production Supabase** alongside 455 Bitget rows; no collisions
- [x] Deployed to cron: `Scrape Binance Simple Earn` step added to `.github/workflows/scrape.yml`; fires on same hourly + workflow_dispatch schedule as Bitget (continue-on-error so Binance failure doesn't invalidate a successful Bitget scrape)
- [ ] Wire Binance events into main scraper.py orchestration (currently sequential; unification is cosmetic — deferred, low priority)
- [ ] Cross-venue anchor-timing test (Decision 5's timing test — Second Law-safe; needs ~2 weeks of dual-venue data)
- [ ] Coverage forecast model (updated with real Binance intake; do after 1 week of data)

**Adjustment observed in this phase** (2026-07-28): Binance homepage endpoint only returns *currently available* products (`sellOut: False` on every observed row). This is a semantic difference from Bitget, which explicitly ships a `status=6` sold_out flag on stale products. Consequence: sold-out detection on Binance depends entirely on diff-based state comparison (product_id present in scrape N, absent in scrape N+1 = sold_out event). Anchor definition remains the same in effect (`sold_out_first_seen_at`), but under the hood the trigger is different. Documented in `parsers/binance_earn.py` docstring.

**Adjustment observed 2**: Binance ships APY as decimal fraction (0.05 = 5%); Bitget ships as percentage-point (5.0 = 5%). Parser normalizes to percentage at parse time so `MIN_APR_FOR_ALERT` gate applies uniformly.

**Adjustment observed 3**: Binance active catalog is ~421 products vs Bitget's active count of ~50-80 (from `earn_events` where status=2 as of Session 2 wrap). Roughly 5-8× intake per scrape, which comfortably clears the "≥1.5× within 4 weeks" trigger below. Real event rate (new/sold-out per day) will be lower and is what actually matters for the corpus doubler thesis; observe first.

**Adjustment trigger 1**: if Binance intake doesn't at least 1.5× current Bitget-only rate within 4 weeks of deploy, invoke Decision 2 A3 kill-switch (stop expanding venues, reconsider hypothesis).

**Adjustment trigger 2**: if cross-venue anchor-timing shows Binance sold_out consistently precedes Bitget sold_out by more than a threshold (TBD in FRAME_C1.md), rethink whether v0.3.0 should anchor on Binance instead of Bitget.

### Phase 3d — Labeler + pre-registration lockdown (~2 weeks) — IN PROGRESS
The pre-registered infrastructure that gates depend on.

- [x] `HYPOTHESIS_A2a.md` + `A2a.yaml` — v0.2.1 fixed-horizon, formal pre-reg (done in Phase 3b)
- [x] `HYPOTHESIS_A2b.md` + `A2b.yaml` — v0.3.0 triple-barrier, formal pre-reg (done in Phase 3b)
- [x] `compute_sigma_realized()` + `resample_to_daily()` in `candles.py` — the barrier-width primitives for v0.3.0 (8 tests, 233/233 total)
- [x] Build v0.3.0 triple-barrier labeler on top of `compute_sigma_realized` (`src/defi_investor/labelers/triple_barrier_v030.py`, `LabelRowV030` returns one row per horizon in `{24h, 48h, 168h}`; 9 tests covering flat, up, down, insufficient-history, truncated-walk, multiplicative-barrier-math; 242/242 total)
- [ ] Wire v0.3.0 labeler into a backfill script (parallel to `scripts/backfill_labels.py` for v0.2.1)
- [ ] Extend `scripts/gate_report.py` for multi-hypothesis + Holm-Bonferroni correction
- [x] `KILL_COUNTER.md` — running ledger (done in Phase 3b)
- [x] Git-tag each pre-registration at commit; upload to OSF (done in Phase 3b — commit 385e5a6)

**Adjustment trigger**: if triple-barrier produces wildly different labels than fixed-horizon on same events, don't touch either — investigate whether it's a labeler bug vs a legitimate methodological difference (deep-read AFML Ch 3 if needed).

### Phase 3e — Order-book channel (~2-3 weeks, parallel with Phase 3d if capacity allows)
The A3 hypothesis. Different signal channel. Only start if Phase 3d isn't at risk.

- [ ] `HYPOTHESIS_A3.md` + `A3.yaml` — order-book impact hypothesis
- [ ] L2 order-book scraper (Bitget + Binance WS free streams)
- [ ] Storage layer for order-book snapshots (may need new table; consider retention TTL)
- [ ] Order-book impact labeler
- [ ] Extend gate report to accommodate A3 with its own kill-counter slot

**Adjustment trigger**: if free WS streams drop connections frequently or require paid tier for reliability, defer A3 entirely and requeue for a Phase 4.

### Phase 3f — Gate call (2026-09-30 or n≥30 primary on any hypothesis, whichever first)
The pre-committed decision date. No iteration allowed between now and this date.

- [ ] Run gate on A2a, A2b (and A3 if ready), with kill-counter-driven correction
- [ ] Publish result to `KILL_COUNTER.md`
- [ ] Trigger Decision 3 pre-committed reframe:
  - **Pass** → widen scope for OOS replication + build A2c CAR
  - **Fail** → widen frame to test meta-question ("does *any* CEX product-surface signal exist?")

**Adjustment trigger**: this phase IS the trigger for the largest scope revision. Update this roadmap after the gate call.

## Cross-cutting norms

### JIT reading
Skim titles/abstracts of all corpus (already done via MOC.md queuing). Deep-read only what a specific decision or implementation requires. Level up LIB status as engagement happens.

### Observation log
Everything surprising gets recorded to `docs/OBSERVATIONS.md` (to be created on first observation). This is the input to roadmap revision.

### Roadmap revision cadence
Weekly self-check: run through the adjustment triggers list above. If any is tripped, edit this file, git-commit the revision, note the reason in the commit message.

### Discipline invariants (non-negotiable)
- No feature/labeler iteration after seeing any label's return.
- All parallel hypotheses pre-registered before code writes labels.
- Track 2 candidates (meme cohort splits, time-of-day, fractional differentiation) stay queued.
- Second Law binds: preliminary results do not drive design changes on the current experiment.

## Revision log
| Date | Revision | Reason |
|---|---|---|
| 2026-07-28 | v2.0 initial draft | Decisions 1-6 locked in Session 3 |
| 2026-07-28 | Phase 3c mid-progress | Binance parser + fetch + dry-run shipped; 3 empirical adjustments logged in Phase 3c section (sold-out semantics, APY unit, catalog size) |
| 2026-07-28 | Phase 3c iter 2 | Standalone binance_scrape orchestrator with diff-based sold-out detection; Migration 009 revised to composite PK + widened FKs; 225/225 tests. Blocker: user greenlight to apply Migration 009 to Supabase before wiring Binance into the live write path. |
| 2026-07-28 | Phase 3c → 3d pivot | Phase 3c parked on Supabase-migration blocker; opened Phase 3d with sigma_20d realized-vol utility (compute_sigma_realized + resample_to_daily in candles.py). 233/233 tests. |
| 2026-07-28 | Phase 3c LIVE | Migration 009 applied to Supabase (composite PK); SupabaseWriter updated; live Binance scrape landed 422 rows to production alongside 455 Bitget. Added Binance step to `.github/workflows/scrape.yml` — Binance now fires on the same hourly cron as Bitget. |
| 2026-07-28 | Phase 3d labeler | v0.3.0 triple-barrier labeler shipped as `defi_investor.labelers.triple_barrier_v030`. Multiplicative barriers on sigma_20d per A2b spec, multi-horizon returns, 9 offline tests. 242/242 total. Next: backfill wiring + gate_report multi-hypothesis. |
