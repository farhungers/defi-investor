---
id: LIB_0026
title: "Walk Forward Correlation: A Diagnostic for Over-Fitting and Structural Edge in Trading Strategy Optimisation"
authors: ["(unknown - to identify on read)"]
year: "(unknown)"
type: paper
source_path: "reaserch/operator suggestions/Walk Forward Correlation A Diagnostic for Over-Fitting and Structural Edge in Trading Strategy Optimisation.pdf"
tags: [walk-forward, correlation, overfitting, structural-edge, diagnostic]
themes: [validation]
links: [LIB_0002, LIB_0027]
status: unread
last_touched: 2026-07-28
---

## Thesis
Walk-forward correlation is a diagnostic that distinguishes between overfitting artifacts and genuine structural edge in a trading strategy. Likely: measures correlation between in-sample and out-of-sample performance; low correlation = overfit, high = structural.

## Key claims (to populate on read)
- Populate after skim.

## Relevance to defi-investor
Complements de Prado's Purged CV and Deflated Sharpe. If we ever tune any labeler hyperparameter, walk-forward correlation is a lightweight sanity check that our tuning isn't just chasing noise.

## Open questions
- How does this relate to de Prado's combinatorial purged cross-validation? Additive or alternative?

## Related notes
- LIB_0002 — Deflated Sharpe (companion overfitting diagnostic)
- LIB_0027 — Walk-Forward Optimization (the technique this is diagnosing)
