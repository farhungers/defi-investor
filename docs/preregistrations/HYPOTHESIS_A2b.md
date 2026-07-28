---
hypothesis_id: A2b
frame_id: FRAME_C1
name: "Bitget+Binance Earn sold-out predicts short-horizon return (triple-barrier labeler)"
version: 1
registered: 2026-07-28
registration_note: "Genuine pre-registration. Labeler v0.3.0 (triple-barrier) does not yet exist; this document specifies what it MUST do before it is built."
status: draft
---

# HYPOTHESIS_A2b

Under FRAME_C1 (informed-positioning detection on CEX). Kill counter position: 2.

Complement to A2a: same event class and universe, different labeler methodology. Tests whether the hypothesis holds under de Prado Ch 3 triple-barrier labels, which relax the fixed-horizon assumption.

## Hypothesis

When an Earn program on Bitget or Binance sells out, the underlying coin's Bitget spot price is more likely to hit an upper volatility-scaled barrier than a lower one within a time-scaled window.

## Null hypothesis (H0)

Post-event triple-barrier outcomes are symmetric — upper and lower barrier hits are equally likely — after accounting for known confounds.

## Labeler spec (pre-registered; code TBB)

- **Labeler ID**: `v0.3.0` (to be built)
- **Type**: Triple-barrier (de Prado Ch 3, LIB_0001)
- **Anchor**: same as A2a — `sold_out_first_seen_at`
- **Upper barrier**: `k_upper × sigma_20d` where `sigma_20d` is the 20-day realized volatility estimated on the anchor date. `k_upper = 2.0` (pre-committed; NOT tunable).
- **Lower barrier**: `k_lower × sigma_20d`, `k_lower = 2.0` (symmetric).
- **Time barrier**: {24h, 48h, 168h} — CV search space per Decision 5.
- **Price source**: Bitget spot 1m klines.
- **Label**: {+1 (upper hit first), -1 (lower hit first), 0 (time barrier hit first)}.
- **Exclusions applied**: same as A2a.

## Gate criteria

All of the following must PASS on the primary universe at the decision date. Family-wise correction applied per KILL_COUNTER.md.

1. `P(label = +1) > P(label = -1)` in observed labels — upper barrier asymmetry
2. Binomial test on +1 vs -1 counts: `p < corrected alpha` where corrected alpha = `0.05 / N_registered`
3. `HHI(labels = +1)` (concentration of positive outcomes across events) `<= 0.15`
4. Sign of asymmetry consistent across ≥ 2 of 3 confound splits

Note: PSR-style gate is inapplicable to categorical labels; binomial test substitutes.

## Decision date

**2026-09-30** (hard). Same as A2a.

## Red-team

Inherits A2a red-team items 1-7. Additional considerations specific to triple-barrier:

8. **Regime-driven asymmetry.** In bull regimes, upper barriers hit more often for any coin, event or not. If our primary universe skews to bull-regime windows, "P(+1) > P(-1)" is a regime signal, not an event signal. Mitigation: BTC regime is a confound split (#4 above).
9. **Volatility estimation contamination.** `sigma_20d` is estimated from the 20 days preceding the anchor. If the *pre-event window itself* contains anticipatory positioning (insiders buying before sold-out), volatility is inflated → barriers wider → +1 hit rate looks lower than it should. The bias direction actually works AGAINST detecting real signal; conservative.
10. **`k_upper = k_lower` is a choice.** Symmetric barriers assume the null of "no asymmetry" is 50/50. If there's a natural asymmetry in coin returns (positive skew for altcoins), the null itself is biased. Consider: run a per-hypothesis calibration on `k` values from a control cohort BEFORE gate; note this in amendment if done.
11. **Time-barrier majority.** If most events resolve as "time barrier hit first" (label=0), we have low statistical power on the +1 vs -1 comparison. Report label distribution alongside gate.

## Amendment log

| Date | Change | Reason |
|---|---|---|
| 2026-07-28 | v1 initial pre-registration | Decisions 5 + FRAME_C1 lock. Code to be built. |
