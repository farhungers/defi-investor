# PHASE_2_PLAN — labeling, features, purged CV, PSR gate

**Author:** Vault (Phase 2 kickoff, 2026-07-10)
**Status:** authoritative plan for Phase 2. Reads on top of `CHARTER.md`, `METHOD.md`, `DATA_MODEL.md`, `LAB_CASE.md`.

Phase 1 is still burning (see `PHASE_1_LOG.md`, `PHASE_1_SESSION_2_LOG.md`, `PHASE_1_EXECUTION_PLAN.md`). This document defines what Phase 2 has to ship the moment n grows enough to run the gate. Nothing here fires signals; nothing here is trading. Alerter is Phase 4 — gated on Phase 3 PSR ≥ 0.95.

## 1. What Phase 2 produces

One deliverable: **a reproducible labeled corpus** with the confound tags and uniqueness weights spelled out in `METHOD.md`, ready to be fed to the Phase 3 PSR gate the moment n ≥ 30.

Everything else Phase 2 builds is scaffolding for that.

## 2. Anchor and universe

**Primary universe (H1 "soaking"):** `Savings` products with `max_apy ≥ 50` and a resolved sold-out event.

**Anchor timestamp:** `sold_out_first_seen_at` — the first scrape where the product's status flipped to 6. This is the observable moment saturation is signaled to the market. NOT `start_time` — start_time is pool creation, which happens hours to days before demand actually saturates.

**Anchor precision cap:** cadence-limited. At 15-min scrape cadence, `sold_out_first_seen_at` is accurate to ±15 min — but only for events where we OBSERVED the 2→6 transition (row in `earn_events_status_log`). Events that were already sold-out at the first scrape have unknown true saturation time and are tagged `unlabelable_reason = "stale_anchor"` by the backfill script (METHOD §1.7.1). Excluded from primary; visible in the corpus for provenance.

**Secondary universes (Phase 2.5, if primary has weak signal):** `PosStaking` high-APR pools, `Savings` at 20% ≤ APR < 50%. Report separately per `METHOD.md` §5 — do not merge cohorts to inflate n.

## 3. Label geometry (per `DATA_MODEL.md` §5)

Triple-barrier from de Prado Ch 3.4:

- **T1_UP:** perp mark rises `k_up * ATR(4h, 24)` above anchor close. Default `k_up = 2.0`.
- **T1_DOWN:** perp mark falls `k_down * ATR(4h, 24)` below anchor close. Default `k_down = 2.0`.
- **T2:** vertical time barrier. `T2 = 7 days` for Savings (matches DATA_MODEL default).

Primary label:
- `+1` if T1_DOWN hits first (dumped — H1 predicts this direction)
- `-1` if T1_UP hits first (pumped — hypothesis wrong)
- `0` if T2 expires without either horizontal hit

Secondary label (for meta-labeling): `realized_r = (P_hit - P_anchor) / (k * ATR) * -sign_of_prediction`. Positive = magnitude confirms hypothesis, negative = wrong.

**Sign convention:** the sub-hypothesis (H1) predicts a dump. Label sign is inverted for a sub-hypothesis that predicts a pump. Phase 2 primary universe is H1 only.

**ATR computation:** ATR(period=24, timeframe=4h) using Bitget perp candles for `<coin>USDT`. If the perp doesn't exist for the coin, fall back to spot. If spot doesn't exist, event is unlabelable — tag as such, exclude from primary.

## 4. Features (starter set)

Live-computable from `earn_events` + candles:

| Feature | Source | Note |
|---|---|---|
| `apr_at_anchor` | `earn_events.max_apy` at sold_out | Log-scaled for the model |
| `tier_count` | `len(earn_events.tiers)` | 1 = bait, ≥2 = ladder |
| `per_user_cap_underlying` | `earn_events.per_user_cap_underlying` | Log-scaled |
| `family` | `earn_events.second_biz_line` | Categorical |
| `time_to_sold_out_hours` | `sold_out_first_seen_at - start_time` | Fast burn = high demand |
| `days_since_start_time` | anchor - start_time | Same as above but daily granularity |
| `cohort_apr_active_count` | `context.cohort_context` at anchor | How saturated the APR band is |
| `cohort_apr_sold_count` | same | |
| `cohort_median_life_d` | same | |
| `atr_4h_at_anchor` | candles | Volatility level |
| `perp_vol_24h_prior` | candles | Liquidity proxy |
| `perp_ret_prior_24h` | candles | Trend prior |
| `perp_oi_pct_change_prior_24h` | Bitget OI endpoint | KOL proxy per METHOD §1.3 |

**Feature exclusions:** anything that reads price after the anchor. This is a look-ahead trap — the label already consumes future price.

## 5. Confound tags (per METHOD §1)

Computed at label time, stored on the label row (not the event row):

- `within_7d_of_tge` — first Bitget candle within 7d of anchor
- `known_vest_unlock_within_3d` — best-effort from TokenUnlocks / project docs. Phase 2 v1 leaves this null; Phase 2.5 adds the scrape.
- `total3_pct_change_7d` — TOTAL3 index change over the 7d ending at anchor
- `perp_oi_pct_change_prior_24h` — OI delta
- `bitget_listing_age_days` — days since first Bitget candle for the coin

Rows with `within_7d_of_tge = True` are excluded from the primary PSR calc but reported separately per METHOD §1.1.

## 6. Storage — Supabase

Add a new table (migration `db/migrations/003_add_labels.sql`, applied when Phase 2 code ships):

```sql
CREATE TABLE IF NOT EXISTS earn_event_labels (
    product_id TEXT NOT NULL REFERENCES earn_events(product_id),
    anchor_ts TIMESTAMPTZ NOT NULL,
    labeler_version TEXT NOT NULL,        -- bump on any labeler change
    label INTEGER,                        -- +1 / -1 / 0 / NULL if unresolved
    realized_r NUMERIC,
    barrier_hit TEXT,                     -- 'T1_UP' | 'T1_DOWN' | 'T2' | NULL
    barrier_hit_ts TIMESTAMPTZ,
    anchor_close_price NUMERIC,
    atr_4h_at_anchor NUMERIC,
    avg_uniqueness NUMERIC,
    -- feature snapshot at anchor
    features JSONB,
    -- confound tags
    within_7d_of_tge BOOLEAN,
    known_vest_unlock_within_3d BOOLEAN,
    total3_pct_change_7d NUMERIC,
    perp_oi_pct_change_prior_24h NUMERIC,
    bitget_listing_age_days INTEGER,
    -- provenance
    candles_provenance JSONB,             -- {url, fetched_at, sha256}
    computed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (product_id, anchor_ts, labeler_version)
);

CREATE INDEX earn_event_labels_anchor_idx ON earn_event_labels(anchor_ts);
CREATE INDEX earn_event_labels_resolved_idx
    ON earn_event_labels(anchor_ts)
    WHERE label IS NOT NULL;
```

Labeler version is a mandatory part of the PK: any labeler change means re-labeling the entire corpus. Do NOT overwrite in place.

## 7. Purged K-Fold CV

Implemented in `src/defi_investor/backtest/cv.py` from de Prado Ch 7. Label intervals are a `pd.Series` indexed by `anchor_ts`, valued by `barrier_hit_ts`. `PurgedKFold.iter_folds()` yields `Fold` records with train / test integer positions plus purge and embargo counts for reporting.

**Fold count:** `n_splits = 3` at n = 30 primary decision, `n_splits = 5` at n = 100 (per METHOD §3.3).

**Embargo:** `embargo_fraction = 0.01` (de Prado Ch 7.4). At 30 events spanning ~4 months, that's ~1.2 days of exclusion after each fold.

## 8. PSR / DSR gate

Implemented in `src/defi_investor/backtest/stats.py`: `psr`, `bet_stats`, `hhi`, `average_uniqueness`.

**Gate criteria at n = 30 (from `METHOD.md` §2.4):**

1. Sign of mean R matches predicted sign for H1 (`+1`)
2. `PSR against SR* = 0 ≥ 0.95`
3. `HHI positive ≤ 0.15` — edge diversified, not driven by 1-2 outliers
4. `median R / mean R ≥ 0.5` — mean not distorted by fat tails
5. Sign consistency across at least 2 of 3 confound splits (age, regime, control-arm)

All five must pass. Any one fails → halt per CHARTER kill criterion.

## 9. Uniqueness weights

Multiple Earn events on the same coin within a T2 window overlap. Compute `average_uniqueness` per de Prado Ch 4.4 (implemented in `src/defi_investor/backtest/stats.py`). This is what deflates raw n to effective n for the PSR call.

## 10. Pipeline

```
data/raw/*.html                                            (Phase 1)
    ↓ parse
earn_events (Supabase)                                     (Phase 1, live)
    ↓ candles fetch
Bitget perp candles                                        (Phase 2)
    ↓ triple-barrier
earn_event_labels (Supabase)                               (Phase 2)
    ↓ feature build
feature matrix                                             (Phase 2)
    ↓ PurgedKFold + PSR
Phase 3 report                                             (Phase 3 gate)
    ↓ if all 5 gates pass
Phase 4 alerter                                            (Phase 4)
```

## 11. Workflows

- `.github/workflows/label.yml` — nightly cron. Walk `earn_events` where `sold_out = true` and no `earn_event_labels` row exists for the current labeler_version. For each: fetch candles, compute barriers, upsert label. Runs at 04:00 UTC.
- `scripts/preview_shadow.py` — manually runnable. Reads current labels, reports what WOULD trigger a Phase 4 alert if the PSR gate were open. Logs only, no Telegram.
- `scripts/gate_report.py` — runnable when n ≥ 30. Produces the METHOD §4.3 report format. Halts if any of the 5 gates fails.

## 12. What NOT to do (per METHOD §5)

- Do not iterate the label window after seeing a poor result.
- Do not merge H1 / H2 / H3 into one PSR call to inflate n.
- Do not exclude events post-hoc. Predefine exclusions in the labeler. Version bump if criteria change.
- Do not report annualized Sharpe without PSR.
- Do not call anything a signal until it passes the 5 gates in `METHOD.md` §2.4.

## 13. Handoff — what a next-session Vault needs

1. `db/migrations/003_add_labels.sql` applied to Supabase.
2. `src/defi_investor/backtest/cv.py` + `stats.py` built from de Prado Ch 7 + Ch 14.
3. `src/defi_investor/candles.py` fetching perp OHLCV from Bitget public endpoints.
4. `src/defi_investor/labeler.py` computing triple-barrier per event.
5. `src/defi_investor/features.py` computing feature snapshot at anchor.
6. `scripts/backfill_labels.py` + nightly workflow.
7. `scripts/preview_shadow.py` for eyeballing while pilot burns.
8. `scripts/gate_report.py` for the Phase 3 gate.

Once (1)-(7) are green and running, n accumulates on its own. Phase 3 gate is a manual call once n ≥ 30.

— Vault, Phase 2 planning, 2026-07-10
