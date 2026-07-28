---
id: LIB_0001
title: "Advances in Financial Machine Learning"
authors: ["López de Prado, Marcos"]
year: 2018
type: book
source_path: "reaserch/operator suggestions/_Advances_in_Financial_Machine_Learning_-_Marcos_Lopez_de_Prado.pdf"
tags: [de-prado, methodology, backtest-overfitting, purged-cv, meta-labeling, triple-barrier, fractional-differentiation]
themes: [discipline, validation]
links: [LIB_0002]
status: integrated
last_touched: 2026-07-28
---

## Thesis
Financial ML fails because researchers apply generic ML techniques to non-i.i.d. financial data. The book prescribes techniques (labels, features, cross-validation, position sizing, backtest evaluation) that respect the peculiarities of financial time series.

## Key claims
- **Triple-barrier labels (Ch 3)** — dynamic upper/lower/time barriers scaled by volatility. Beats fixed horizons because they adapt to market state. Direct input to Hypothesis A2b.
- **Meta-labeling (Ch 3)** — a secondary ML model that filters primary-model signals. Boosts precision, not recall. Direct input to Decision 5's D1 pick.
- **Purged K-Fold CV (Ch 7)** — remove training samples whose labels overlap with test samples in time. Core defense against leakage in path-dependent labels.
- **Deflated Sharpe / PSR (Ch 14)** — correct Sharpe for selection bias under multiple testing. See LIB_0002 for the standalone paper.
- **Fractional differentiation (Ch 5)** — preserves memory while making series stationary. Not yet applied in defi-investor.
- **Second Law: do not research under the influence of a backtest.** Central discipline principle of the whole project. Reason CHARTER §5 exists.

## Relevance to defi-investor
This is the load-bearing methodological reference. Directly cited by:
- `src/defi_investor/backtest/cv.py` — PurgedKFold implementation (Ch 7)
- `src/defi_investor/backtest/stats.py` — PSR + uniqueness (Ch 14)
- Planned v0.3.0 labeler — triple-barrier (Ch 3)
- Planned meta-labeling layer per Decision 5 (Ch 3)
- CHARTER §5 kill criteria and Second Law discipline

## Open questions
- Ch 11 backtest overfitting: do we have enough hypotheses in flight to warrant the deflation math beyond what's already in `psr()`?
- Ch 8 feature importance: worth applying to whichever labeler passes first gate?
- Ch 10 bet sizing: only relevant post-gate but should be scoped now.

## Related notes
- LIB_0002 — Deflated Sharpe Ratio (Bailey & de Prado 2014, standalone paper form)
- (future) permanent/second_law.md — synthesis of the discipline principle across de Prado, Popper, Hamming
