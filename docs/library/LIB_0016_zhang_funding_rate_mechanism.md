---
id: LIB_0016
title: "Funding Rate Mechanism in Perpetual Futures"
authors: ["Zhang, Tianyang"]
year: 2026
type: paper
source_path: "reaserch/operator suggestions/ssrn-6185958.pdf"
tags: [funding-rate, perpetual-futures, market-microstructure, arbitrage, liquidation-cascades]
themes: [microstructure]
links: [LIB_0015, LIB_0017]
status: skimmed
last_touched: 2026-07-28
---

## Thesis
Funding rates in crypto perpetual futures are best modeled as an *algorithmic feedback rule*, not a passive transfer. Zhang derives a continuous-time equilibrium where a linear funding rule induces mean-reverting basis with derivable stability conditions.

## Key claims (from abstract)
- Continuous-time model with risk-constrained arbitrageurs + momentum speculators.
- Linear funding → endogenous mean-reverting basis.
- Stability condition + welfare-optimal feedback strength are derivable.
- Update interval, funding caps, and clamp-style piecewise-linear rules (used by major exchanges) meaningfully affect basis volatility and funding tails.
- Jump-and-crisis extension: liquidation-driven crashes produce large negative basis spikes with slow recoveries.

## Relevance to defi-investor
- Direct theoretical basis for using funding rates as a confound or signal channel.
- Clamp/cap behavior across Binance/Bitget matters if we ever add funding to the confound stack.
- "Liquidation-driven basis spikes" describes exactly the kind of event our labeler might either see as noise or (if we're smart) exploit as a leading indicator.

## Open questions
- Does the model imply Bitget's funding rate leads or lags Binance's? Empirical test?
- Do the "slow recoveries" post-liquidation overlap with our 24h/48h label windows?

## Related notes
- LIB_0015 — BitMEX Research empirical companion
- LIB_0017 — Crypto perp temporal dynamics
