---
hypothesis_id: A3
frame_id: FRAME_C1
name: "Order-book depth impact around Earn sold-out events predicts short-horizon return"
version: 1
registered: 2026-07-28
registration_note: "Pre-registered. Neither the order-book scraper nor the impact labeler exists yet; this document specifies what they MUST do before being built."
status: draft
---

# HYPOTHESIS_A3

Under FRAME_C1 (informed-positioning detection on CEX). Kill counter position: 4.

**Different signal channel from A2a/A2b.** Instead of asking "does the event predict price?" this asks "does the *order-book response* to the event predict price?" — a microstructure hypothesis. Rationale: order-book impact is harder for retail chasing to fake (retail rarely places limit orders; impact requires liquidity provider adjustment). If informed positioning is real, it likely shows in the depth curve BEFORE showing in price.

## Hypothesis

When an Earn sold-out event occurs, an asymmetric contraction of the underlying coin's Bitget spot order-book depth on the ask side (relative to bid side) in the 5-minute window preceding the event predicts a positive Bitget spot return in the following 24 hours.

## Null hypothesis (H0)

Pre-event order-book asymmetry is uncorrelated with post-event price movement.

## Labeler spec (pre-registered; code TBB)

- **Labeler ID**: `A3_v0.1.0` (to be built)
- **Type**: Order-book impact
- **Data source**: Bitget spot L2 order-book WebSocket stream (free tier); Binance spot L2 stream as cross-validation
- **Feature**: `depth_asymmetry_5min = (log(depth_ask_top_5_5min_avg) - log(depth_ask_top_5_pre_5min_avg)) - (same for bid side)` computed over the 5-minute window ending at `sold_out_first_seen_at`
- **Anchor**: `sold_out_first_seen_at`
- **Response horizon**: 24h post-anchor Bitget spot log return
- **Label**: `+1` if ask-side contraction ≥ pre-registered threshold `theta_asym`; `-1` if bid-side contraction ≥ threshold; `0` otherwise
- **`theta_asym`**: `0.5` (pre-committed; NOT tunable pre-gate)
- **Exclusions**: no order-book data available, WebSocket gap ≥ 60s in the pre-event window, within 7d of TGE

## Gate criteria

Applied on the subset of primary events where order-book data is available.

1. `E[R_24h | label = +1] > E[R_24h | label = -1]`
2. Difference-in-means t-test: `p < corrected alpha` where corrected alpha = `0.05 / N_registered`
3. `n_labeled >= 30`
4. Order-book data coverage `>= 70%` of primary events (otherwise coverage bias dominates)

## Decision date

**2026-11-30** (hard). Later than A2a/A2b because scraper build is a longer dependency.

## Red-team

*Additional to any red-team items inherited from FRAME_C1.*

1. **Market-maker anticipation of any known event.** MMs pull quotes ahead of ANY expected volatility, not because they have insider info about *this* event. Any pre-event depth contraction may be a general "volatility expected" signal, orthogonal to informed positioning.
2. **Iceberg reveal artifact.** What looks like new depth appearing or disappearing may just be iceberg orders becoming visible or exhausted; no informational content.
3. **Front-running by observers.** Other market participants observing the same public Earn state may front-run based on it. Our "signal" would just measure the reflex of other observers, not informed positioning.
4. **Latency asymmetry.** Bitget WebSocket updates arrive with variable latency (10ms–5s observed empirically for L2 data). Timing errors around the 5-minute pre-event window could smear the signal boundary.
5. **Cross-venue arbitrage response.** Any depth change on Bitget may be pure arb response to a move already occurring on Binance. Not new information; just liquidity migration.
6. **Coverage bias.** Small-cap Bitget-listed coins have thin L2 streams with frequent gaps. If we exclude events with insufficient data, we systematically exclude the events most likely to be manipulation targets. Signal on the remaining set is biased toward mid-caps.
7. **`theta_asym = 0.5` is arbitrary.** Threshold selection matters. Pre-committing removes the tuning temptation but may miss the true optimal threshold. Accepted trade-off for discipline.

## Amendment log

| Date | Change | Reason |
|---|---|---|
| 2026-07-28 | v1 initial pre-registration | Decisions 5 + FRAME_C1 lock. Scraper and labeler both to be built. |
