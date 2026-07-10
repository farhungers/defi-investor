# PHASE_2_SESSION_1_LOG — Vault, Phase 2 kickoff

**Session date:** 2026-07-10
**Identity:** Vault
**Prior:** Phase 1 pilot burning on `*/15` GH Actions cron (see `PHASE_1_LOG.md`, `PHASE_1_SESSION_2_LOG.md`).

## Shipped

**Phase 2 infrastructure — the labeling pipeline is fully runnable.**

- `src/defi_investor/candles.py` — Bitget public perp+spot fetcher. Endpoint verified live. Paginated over 90-day chunks. Wilder ATR helper.
- `src/defi_investor/labeler.py` — triple-barrier `label_event()` per METHOD §5. Anchor at `sold_out_first_seen_at`, k_up=k_down=2.0×ATR(4H,24), T2=7d. Guard rails on missing candles, ATR warmup, unresolved horizon return `unlabelable_reason` rather than fabricate. `LABELER_VERSION = "0.2.1"`.
- `src/defi_investor/features.py` — anchor-time feature snapshot with stable key set. Cohort context, tier structure, per-user cap, family, timing, repeat-coin.
- `src/defi_investor/confounds.py` — best-effort confound tags (`bitget_listing_age_days`, `within_7d_of_tge`, `btc_ret_7d_prior`, `perp_vol_change_prior_24h`). OI-history and TOTAL3 documented as forward-collection only (Bitget has no OI history endpoint; CoinGecko gates market-cap history).
- `src/defi_investor/backtest/cv.py` — `PurgedKFold` + `drop_overlapping` + `apply_embargo`. **Built from de Prado Ch 7 directly, not ported.** Own idioms (`Fold` dataclass, `iter_folds()`).
- `src/defi_investor/backtest/stats.py` — `bet_stats`, `psr`, `hhi`, `average_uniqueness`. **Built from de Prado Ch 14 + Bailey & de Prado 2012 directly.** Own naming (`BetStats`, `psr_vs_zero`).
- `db/migrations/003_add_labels.sql` — `earn_event_labels` table with composite PK on `(product_id, anchor_ts, labeler_version)`.
- `db/migrations/004_confound_proxies.sql` — proxy columns for `btc_ret_7d_prior` and `perp_vol_change_prior_24h`.
- `scripts/backfill_labels.py` — nightly labeler. Idempotent by version. Runs `cohort_context`, `_prior_earn_count_for_coin`, `compute_confounds` per event.
- `scripts/gate_report.py` — METHOD §4.3 report. Corpus breakdown, Sharpe / PSR / HHI / uniqueness-adjusted effective n, three confound splits, purged 3-fold CV, five-gate PASS/FAIL rollup, explicit n-gate line.
- `scripts/quality_dashboard.py` — operator dashboard: events by family, transitions, resolved fraction, confound coverage.
- `scripts/preview_shadow.py` — read-only Phase 4 preview. Never sends Telegram.
- `.github/workflows/label.yml` — nightly 04:00 UTC cron.

**Discipline durables saved to memory:**

- `feedback_no_borrowing_from_siblings.md` — after user caught the initial mm-radar port, rebuilt everything from de Prado directly. Rule: no reads outside `C:\defiINVESTIGATOR\`; ask for reference books instead.
- `feedback_no_premature_signals.md` — cards carry observation content only until PSR gate passes. Refuse "profitable signal in 24h" asks. Layout can be as rich as any inspiration card; body content cannot fabricate entry/stop/TP.

**Tests:** 134/134 green (started this Phase-2 kickoff at 65, +69 covering the new modules).

## What did NOT ship

- Real `perp_oi_pct_change_prior_24h` — Bitget's V2 public API exposes current OI only. Forward-collect via a scraper snapshot step to add this.
- Real `total3_pct_change_7d` — CoinGecko free tier gates market-cap history behind Pro. Using `btc_ret_7d_prior` as macro proxy.
- PoolX scraper for `/earning/launchpool` — deferred; client-rendered, needs Playwright. Not urgent for H1 primary universe.
- Control-arm scraper (Bitget listings without Earn program) per METHOD §1.4.
- Uniqueness weighting applied to the primary PSR call — `average_uniqueness` is available and gate_report computes it, but per-event weight coefficients are not yet applied (harmless at low n; matters at Phase 3).

## Discoveries worth remembering

1. **Anchor precision on pre-existing sold-outs is unrecoverable.** ~73% of the initial sold-out corpus was already `sold_out=true` at scraper birth. Their `sold_out_first_seen_at` reflects discovery, not saturation. Codified as METHOD §1.7.1; backfill tags them `unlabelable_reason="stale_anchor"` and excludes them from primary.
2. **Bitget 1D candles cap at 90 days per request.** My initial `listing_age_days` fetched a 7-year window and always got HTTP 400. Fixed by chunking to 89 days; anything older returns `_LISTING_AGE_CAP = 90` (Phase 3 confound splits at `age >= 30d` are unaffected).
3. **Per-tier APR ladder was hidden in plain sight.** `apyList` was on the main earning page all along; the initial parser flattened it to `max_apy`. 10 of 399 products are multi-tier. Migration `002_add_tiers` fixed this before pilot start.
4. **Bitget has no public OI history endpoint** and CoinGecko free-tier gates historical global data. Two of METHOD §1's confound tags are forward-only until we add snapshot cron or pay for data.

## State handoff

- Repo: 134/134 tests green. 15 commits total. `main` at `6ff1277`. Working tree clean.
- Supabase: `earn_events` at ~399 rows, `earn_event_labels` at 104 rows across 4 labeler versions (0.1.0, 0.1.1, 0.2.0 buggy-confounds, 0.2.1 current). Every version kept via composite PK so we can compare later.
- GH Actions: `scrape.yml` running every 15 min, `health.yml` every 30 min, `label.yml` nightly at 04:00 UTC.
- Telegram: `@Defiinvestor_Bot` alerts on new listings, sold-outs, re-opens, stalls, drift.
- Local `.env` has Supabase creds + GitHub PAT + Telegram bot token + chat id. `.env.example` documents shape.

## Immediate next actions for future Vault

**Nothing to build; watch.** Second Law.

1. Let 7 days pass. Check quality dashboard weekly for the confound-coverage percentages and the resolved-labels count.
2. First live-labeled events will start showing up around 2026-07-16 (7 days after this session's first observed transitions).
3. Once `preview_shadow.py` prints n ≥ 10, run `gate_report.py` as a checkpoint — DO NOT interpret this as the gate; just verify the pipeline output shape.
4. Real Phase 3 gate call is n ≥ 30. Realistic timeline: 2-4 weeks depending on Bitget churn.
5. If any of CHARTER §3 kill criteria trip, halt.

**Genuine work available if impatient (in order of value):**

- Add OI snapshot to the scraper cron (extends `perp_oi_pct_change` from forward-only to backfillable-once-30d-elapses).
- Apply per-event uniqueness weights inside `gate_report.py` (currently computed but not weighted into the PSR call).
- Wire a real TOTAL3 source (paid CoinGecko or CMC).

Everything else is pilot patience.

— Vault, Phase 2 Session 1 close, 2026-07-10
