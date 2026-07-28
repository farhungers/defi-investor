---
hypothesis_id: A2a
frame_id: FRAME_C1
name: "Bitget+Binance Earn sold-out predicts short-horizon return (fixed-horizon labeler)"
version: 1
registered: 2026-07-28
registration_note: "Retroactive registration. Labeler v0.2.1 has been running since Phase 2 (2026-07-10). This document formally registers what was already being tested; prior labels count toward the corpus."
status: draft
---

# HYPOTHESIS_A2a

Under FRAME_C1 (informed-positioning detection on CEX). Kill counter position: 1.

## Hypothesis

When an Earn program on Bitget or Binance sells out (transitions from open state to sold_out state), the underlying coin's Bitget spot price exhibits a positive expected return over short horizons (24h, 48h, 168h/7d).

## Null hypothesis (H0)

Earn sold-out events carry no predictive information about subsequent Bitget spot price movement beyond what is explained by known confounds (BTC regime, listing age, positioning ramp, vest schedule).

## Labeler spec

- **Labeler ID**: `v0.2.1` (existing, at `src/defi_investor/labeler.py`)
- **Type**: Fixed-horizon
- **Anchor**: `sold_out_first_seen_at` from `earn_events`
- **Horizons**: {24h, 48h, 168h} — selected via purged CV per Decision 5 (multi-timeframe is CV search space, not separate hypotheses)
- **Price source**: Bitget spot 1m klines
- **Return metric**: log return from anchor price to horizon price
- **Exclusions applied**: stale_anchor, horizon_not_yet_resolved, no_candles_available, within_7d_of_TGE

## Gate criteria

All of the following must PASS on the primary universe at the decision date. Family-wise correction applied per KILL_COUNTER.md.

1. `mean_r > 0`
2. `PSR(effective_n) >= 0.95` after family-wise correction (currently `0.05 / N_registered`, tightening as counter grows)
3. `HHI(winners) <= 0.15` — winning trades not concentrated in <7 events
4. `median_r / mean_r >= 0.5` — outcome distribution not right-tail-driven
5. Sign of `mean_r` consistent across ≥ 2 of 3 confound splits (age, BTC regime, vol ramp)

## Decision date

**2026-09-30** (hard). If `primary_n < 30` by that date, gate call is "insufficient data" (per FRAME_C1 §6, this counts as a failed gate for that hypothesis at that sample size — reframing pre-committed to trigger).

## Red-team

*How this hypothesis could look real even if it isn't.* (D1 requirement.)

1. **Regime confound.** Earn sold-outs cluster in bull regimes when retail is chasing yield. Measured "signal" could be pure BTC beta. Mitigation: BTC 30d return sign is one of the three confound splits.
2. **Retail-chasing artifact.** Sold-out is a lagging indicator of retail flow, not a leading indicator of insider positioning. Retail sees a coin pumping, piles into Earn, causes sold-out — the pump is already happening. No insider information; sold-out is downstream of the move we think we're predicting.
3. **Anchor timing error.** Our sold-out timestamp is when the scraper *observed* the transition, up to the scraper interval stale (was 15m, now up to 1h). Real transition happened earlier. Timing error smears the signal boundary.
4. **Coincident news.** Earn program sold-outs may correlate with unrelated bullish catalysts (listing announcements, exchange partnerships, product releases). Isolated Earn signal is really an omitted-variable news signal.
5. **Selection bias / survivorship.** Coins that de-listed between event and horizon are dropped. If de-listings correlate with negative post-event returns, mean R is biased upward.
6. **Multiple testing across cohorts.** Without kill counter discipline, easy to find "signal" by slicing (meme vs serious, small-cap vs mid-cap, APR bucket, etc.). Kill counter tracks these; cohort splits require pre-registration.
7. **Reverse causality on our own data.** If Vault (this Claude instance) or the user acts on the signal — even in observation mode — it perturbs the market. Currently mitigated by observation-only cards; would break the moment we act.
8. **Family-wise correction may under-count trials (added 2026-07-28 by Kepler after deep-reading LIB_0002).** The gate correction uses `alpha / N_registered` with `N=3` (A2a, A2b, A3). Under Bailey & de Prado (2014) DSR framework, `N` should be the number of independent **trials**, not hypotheses. Our multi-horizon CV over {24h, 48h, 168h} formally counts as 3 trials per hypothesis, so the effective N is closer to 9. Under Bailey & de Prado's 1/e optimal-stopping rule we've also already exceeded the number of configurations that should be evaluated. Consequence: a marginal PASS on the current Holm-Bonferroni correction (`alpha/3`) may be a false positive under proper DSR (`alpha/9` or DSR with effective N̂). **A marginal gate PASS should be treated with skepticism and re-checked under DSR before any downstream action.** Not amending the correction method mid-experiment (per Second Law); logging this as a red-team acknowledgment instead.

## Amendment log

| Date | Change | Reason |
|---|---|---|
| 2026-07-28 | v1 initial (retroactive) registration | Decisions 5 + FRAME_C1 lock |
| 2026-07-28 | Red-team item #8 added — DSR N-count caveat | Deep-read of LIB_0002 surfaced that our family-wise divisor under-counts trials. No change to gate correction (Second Law); documented as red-team caveat only. |
