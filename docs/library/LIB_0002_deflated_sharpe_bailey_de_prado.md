---
id: LIB_0002
title: "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality"
authors: ["Bailey, David H.", "López de Prado, Marcos"]
year: 2014
type: paper
source_path: "reaserch/your requests/deflated-sharpe.pdf"
tags: [sharpe-ratio, backtest-overfitting, selection-bias, family-wise-correction, non-normality]
themes: [validation]
links: [LIB_0001]
status: skimmed
last_touched: 2026-07-28
---

## Thesis
Reported Sharpe ratios are systematically inflated by two effects: (1) selection bias from picking the best out of many trials, and (2) non-normal return distributions. The Deflated Sharpe Ratio (DSR) corrects for both, giving a probabilistic assessment of whether a Sharpe is real.

## Key claims (from abstract)
- Backtest optimizers search over many strategies, producing **backtest overfitting** — reported Sharpe reflects the maximum, not the true underlying signal.
- Even without optimization, researchers cherry-pick winners — **selection bias** inflates any published Sharpe.
- DSR corrects for both: it deflates the observed Sharpe by (a) number of trials, (b) skew, (c) kurtosis, (d) sample length.
- Yields Minimum Track Record Length and Minimum Backtest Length as practical decision aids.

## Relevance to defi-investor
Directly load-bearing for gate correction in the multi-hypothesis structure (Decision 4 kill-counter architecture). As we register A2a, A2b, (A2c post-gate), A3 → the kill counter grows and the DSR / Holm-Bonferroni correction must scale accordingly.
- `src/defi_investor/backtest/stats.py::psr()` — implements probabilistic Sharpe; needs to be extended toward full DSR when kill counter grows.
- Gate criteria for Hypothesis A2a must reference this correction, not raw Sharpe.

## Open questions
- Does DSR need the actual paper's math or is the AFML Ch 14 summary sufficient? (Deep-read the paper before extending `psr()`.)
- How does DSR compose with our uniqueness deflation? Sequential or joint correction?
- What are the assumed distributional priors on the trial set — do our labeler variants meet them?

## Related notes
- LIB_0001 — AFML Ch 14 covers DSR at chapter length
- (future) permanent/family_wise_correction.md — synthesis across DSR, Holm-Bonferroni, kill counter design
