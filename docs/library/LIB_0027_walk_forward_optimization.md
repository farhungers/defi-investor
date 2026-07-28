---
id: LIB_0027
title: "Walk-Forward Optimization"
authors: ["(unknown - to identify on read)"]
year: "(unknown)"
type: paper
source_path: "reaserch/operator suggestions/Walk-Forward Optimization.pdf"
tags: [walk-forward, optimization, backtesting, hyperparameter-tuning]
themes: [validation]
links: [LIB_0002, LIB_0026]
status: unread
last_touched: 2026-07-28
---

## Thesis
Walk-forward optimization: iterate through time, optimizing on a rolling in-sample window and evaluating on the immediately-following out-of-sample window. Standard technique for time-series strategy development.

## Key claims (to populate on read)
- Populate after skim.

## Relevance to defi-investor
- We currently use Purged K-Fold (de Prado Ch 7) which is a stricter cousin. Walk-forward is more permissive and closer to how real trading would deploy.
- If we ever ship a live strategy, walk-forward evaluation is the honest final check.

## Open questions
- Do we need walk-forward alongside purged CV, or is purged CV strictly stronger?

## Related notes
- LIB_0026 — Walk-forward correlation (diagnostic)
- LIB_0002 — Deflated Sharpe
- LIB_0001 — de Prado Ch 7 Purged CV
