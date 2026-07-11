# REFERENCES — book stack and phase mapping

Physical files live at `C:\defiINVESTIGATOR\resaerchBOOKS\`. Per memory
`feedback_no_borrowing_from_siblings.md`, this project is built from these
references directly — no reads outside `C:\defiINVESTIGATOR\`.

## Primary reference

**López de Prado, Marcos.** *Advances in Financial Machine Learning.* Wiley, 2018.
ISBN 978-1-119-48208-6.
File: `resaerchBOOKS/Advances_in_Financial_Machine_Learning_-_Marcos_Lopez_de_Prado.pdf`

### What's already implemented from AFML

| Section | Topic | Where |
|---|---|---|
| §3.4 | Triple-Barrier Method | `src/defi_investor/labeler.py::label_event` |
| §4.4 | Average Uniqueness | `src/defi_investor/backtest/stats.py::average_uniqueness` |
| §7.4 | Purged K-Fold CV | `src/defi_investor/backtest/cv.py::PurgedKFold` |
| §7.4 | Embargo | `src/defi_investor/backtest/cv.py::apply_embargo` |
| §14.7.2 | Probabilistic Sharpe Ratio | `src/defi_investor/backtest/stats.py::psr` |
| §14.7.2 | HHI concentration | `src/defi_investor/backtest/stats.py::hhi` |

Also uses Bailey & de Prado (2012) — the standalone PSR paper. Formula
already in METHOD §4.1; no re-derivation needed.

### Queued for the Phase 3 gate (n ≥ 30)

- **§4.5 Bagging Classifiers and Uniqueness.** Extends §4.4. Only matters
  if we ever fit an ensemble over the labels — probably Phase 4.
- **§4.6 Return Attribution.** Attribution-weighted returns. A stricter
  effective sample size than plain uniqueness deflation. Feed into
  `psr_effective` to tighten the Phase 3 gate.
- **§4.7 Time Decay.** Older events downweighted by an exponential kernel.
  Matters when the pilot spans regime shifts. Wire into gate_report's
  primary R computation as an option flag.

### Queued for n ≥ 100 (Phase 3 tertiary)

- **§7.5 Combinatorial Purged CV.** Extends §7.4. Multiple test paths per
  fold. Ch 11 in AFML provides the full backtest evaluation framework.
- **§14.7.3 Deflated Sharpe Ratio.** METHOD §4.2 already commits to skip
  DSR at single-hypothesis n=30. Reintroduce only when we start comparing
  sub-hypotheses (H1 vs H2 vs …).

### Deliberately not queued

- **§3.6-3.8 Meta-Labeling.** Requires a working primary signal first.
  Do not build until Phase 3 gate passes.
- **Ch 5 Fractionally Differentiated Features.** Only if we ever add
  regression-based features beyond the triple-barrier labels.
- **Ch 6 Ensemble Methods, Ch 8 Feature Importance, Ch 13 Bet Sizing.**
  All post-Phase-3.

## Secondary reference

**López de Prado, Marcos.** *Machine Learning for Asset Managers.*
Cambridge University Press (Elements in Quantitative Finance), 2020.
ISBN 978-1-108-79289-9.
File: `resaerchBOOKS/Machine_Learning_for_Asset_Managers_-_Marcos_M_Lopez_de_Prado.pdf`

Only relevant post-Phase 3 or if primary universe grows past n = 100.

### Queued sections

- **Ch 5 Financial Labels.** Concise re-derivation of AFML Ch 3 with
  updated meta-labeling patterns. Reference if we revisit label schema.
- **Ch 6 Feature Importance Analysis.** Cluster-robust importance
  measures. Matters at Phase 4 when we've collected enough features
  beyond the triple-barrier label to run a proper attribution.
- **Ch 8 Testing Set Overfitting.** The "False Strategy" theorem
  (Appendix B). Directly relevant if we ever run more than one
  hypothesis in parallel and need to defend against selection bias
  beyond what DSR handles.

## Reading protocol

- No sibling-directory reads (per memory).
- No paraphrasing from web summaries — go to the PDF.
- When implementing a formula, cite the exact section in the module
  docstring (see `stats.py` and `cv.py` for the pattern).
- If a section's implementation requires a Python library not already
  in `pyproject.toml`, that dependency must be justified in the PR
  message.
