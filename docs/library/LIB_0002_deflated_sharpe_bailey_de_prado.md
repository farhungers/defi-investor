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
status: deep_read
last_touched: 2026-07-28
---

## Thesis
Reported Sharpe ratios are systematically inflated by (a) selection bias from picking the best of N trials, and (b) non-normal return distributions. The Deflated Sharpe Ratio (DSR) is a single statistic that corrects for both, yielding the probability that the true SR exceeds a threshold specifically inflated by the number of trials.

## Key equations (verbatim from the paper)

**Expected maximum Sharpe over N independent trials** (Eq. 1, derived in Appendix 1):

    E[max{SR_n}] ≈ E[{SR_n}] + sqrt(V[{SR_n}]) × ( (1-γ)·Z^-1[1-1/N] + γ·Z^-1[1-1/(N·e)] )

where γ ≈ 0.5772 is Euler-Mascheroni, Z^-1 is the standard normal quantile function, and V[{SR_n}] is the variance across trial-SR estimates.

**Deflated Sharpe Ratio** (Eq. 2):

    DSR = Z[ (SR - SR_0) × sqrt(T-1) / sqrt(1 - γ3·SR + ((γ4-1)/4)·SR²) ]

where:
- SR is the selected strategy's observed Sharpe (non-annualized)
- SR_0 is the deflated rejection threshold — equals sqrt(V[{SR_n}]) × (the parenthesized term in Eq. 1) — i.e., the expected-max-SR under H0: true SR = 0
- T is the sample length (number of returns observations)
- γ3, γ4 are the skewness and kurtosis of the selected strategy's returns
- Z is the standard normal CDF

**Effective number of independent trials** (Eq. 9, Appendix 3), when the M attempted trials are correlated with average ρ̂:

    N̂ = ρ̂ + (1 - ρ̂)·M

so ρ=0 (independent) → N̂=M, ρ=1 (perfectly correlated) → N̂=1. Interpolates linearly; a Fisher-transform refinement is possible.

## Numerical anchor (§A Numerical Example, page 10)

Given SR=2.5, N=100 trials, T=1250 daily returns (5y), V[{SR_n}]=0.5, γ3=-3, γ4=10:
- SR_0 ≈ 0.1132 (non-annualized) — this is the threshold the SR must beat to demonstrate skill.
- DSR ≈ 0.9004 → REJECT at 95% confidence.

If the researcher had run only 46 trials (not 100), DSR would have been ≈ 0.9505 → accept. Same underlying SR, different N, different verdict. This is the whole point.

## Relevance to defi-investor

### Where DSR should be used

- **A2a gate criterion #2** currently reads "PSR(effective_n) ≥ 0.95 after family-wise correction, corrected alpha = 0.05 / N_registered." Our implementation in `src/defi_investor/backtest/stats.py::psr()` computes PSR against a zero benchmark. DSR is the PROPER family-wise correction for the Sharpe path: it substitutes SR_0 (which depends on N) for the zero benchmark. Currently we implement family-wise correction by tightening alpha rather than by inflating SR_0 — algebraically equivalent under normality but under-corrects for non-normality since alpha-tightening doesn't touch the γ3/γ4 terms.

- **A2b (binomial) and A3 (Welch t) don't use PSR** so DSR doesn't apply there. The Holm-Bonferroni step-down in `family_wise.holm_bonferroni` remains the correct correction for those.

### Where uniqueness deflation fits

- Uniqueness deflation reduces T (the effective sample size) via label-span concurrency (de Prado Ch 4.4). It appears in the DSR denominator through the `sqrt(T-1)` factor.
- Uniqueness and DSR are ORTHOGONAL corrections: uniqueness → T; DSR → SR_0.
- Apply sequentially: (1) shrink T by uniqueness, (2) compute DSR with the shrunk T.

### Where N should come from

Not just the kill counter. The kill counter (N=3 currently: A2a, A2b, A3) is the count of pre-registered *hypotheses*. But the DSR N is the number of *independent trials* — which for A2a specifically includes the CV search over horizons {24h, 48h, 168h} plus any other tuning done pre-gate. If we cross-validate 3 horizons on A2a alone, our effective N for A2a's DSR is 3, and using the family kill-counter N=3 as-if-independent would DOUBLE-COUNT unless we're careful. Eq. 9 (correlation-aware N̂) is the right tool here.

## Extension work implied for this project

- **Extend `psr()`** in `stats.py` to accept optional `(v_trials_sr, n_trials, skew, kurt)` and produce DSR when all provided.
- **Update `gate_report.py`** to compute DSR instead of PSR-vs-zero when we're gating a Sharpe-family hypothesis inside a multi-hypothesis family. Currently we do alpha-tightening; that's an incomplete correction.
- **Amendment implication**: A2a.yaml says `correction_method: holm_bonferroni`. Switching to DSR is a change to the correction method. Under our pre-registration protocol this needs an amendment log entry in HYPOTHESIS_A2a.md BEFORE any label rows are re-gated. Not urgent (no gate call before 2026-09-30), but flag for the pre-gate discipline pass.

## Discussion points from the paper worth remembering

- **"A backtest where the researcher has not controlled for the extent of the search is worthless"** — the paper's normative claim, useful ammunition when someone reports a Sharpe without disclosing N.
- **Holdout method does NOT prevent backtest overfitting** — running holdout ~20 times at α=5% gives a "false positive is expected" regime. Justifies our purged-KFold + kill-counter architecture over a simple train/test split.
- **Memory effects make overfitting particularly damaging** — patterns that overfitted-in-sample tend to REVERSE out-of-sample when the underlying process has mean reversion. This is why in-sample Sharpe of 2.5 can flip to negative live PnL, not just decay to zero.
- **Optimal-stopping heuristic (page 10-11)**: sample 1/e ≈ 37% of theoretically-justifiable configurations, then take the next one that beats them all. This is the secretary-problem answer and gives a principled cap on multiplicity. For us: we've committed to 3 hypotheses × up to 3 horizons = 9 configs; 1/e of that is ~3; we've already exceeded the optimal stopping. Consequence: DSR N should be N≥9 for A2a, not 3.

## Open questions after deep-read

- **Does the "3 horizons × 1 hypothesis" for A2a count as 3 trials or 1?** Depends on whether CV horizon selection is a "trial" in Bailey/de Prado's sense. Reading page 8: "trial" = one full backtest with a distinct strategy. Multi-horizon evaluation per hypothesis IS multiple trials under that definition. Decision needed pre-gate.
- **What ρ̂ do we assume between A2a, A2b, A3?** Same underlying event set (sold-out anchors), different labelers on the same data → highly correlated. Naive ρ̂ ≈ 0.7 → N̂ ≈ 0.7 + 0.3×3 = 1.6, which is smaller than the raw kill-counter of 3. Rougher correction. Justifiable in an amendment.
- **Should we implement PBO (Probability of Backtest Overfitting, referenced on p6)** as a companion to DSR? It's a non-parametric CV-based approach that would catch overfitting the DSR itself can miss. Later concern; deep-read the Bailey et al. 2014b PBO paper first.

## Status change log

| Date | From | To | Reason |
|---|---|---|---|
| 2026-07-28 | skimmed | deep_read | Kepler read full paper (14 pages) and extracted equations + implications |
