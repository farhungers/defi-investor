---
frame_id: FRAME_C1
name: Informed-positioning detection on CEX
registered: 2026-07-28
registered_by: Vault
git_commit: (populated at commit time)
osf_id: (populated after OSF upload)
supersedes: none
status: active
---

# FRAME_C1 — Informed-positioning detection on CEX

Pre-registered research frame for the defi-investor project. Locked in Session 3 (2026-07-28) per Decisions 1-6. All hypotheses in this project inherit from this frame.

## 1. The research question

**Who is positioning ahead of a price move on centralized cryptocurrency exchanges, and what publicly-observable signals expose them?**

This is a general question about informed trading in CEX ecosystems. It subsumes many possible hypotheses (Earn programs, futures listings, Launchpools, funding-rate divergences, cross-venue timing anomalies), each of which is one specific answer.

## 2. Why this frame

The narrower question "does Bitget Earn sold-out predict pump-and-dump?" is one instance of the more general question. The broader frame:

- Gives all future hypotheses a coherent intellectual home.
- Matches the operator-curated research corpus (prediction-market informed-trader papers, microstructure work, Kelly sizing, epistemology) which is clearly organized around informed-trading detection.
- Avoids the failure mode of narrow-frame + ad hoc expansion. Any new hypothesis is either "yes, in scope" or "no, out of scope" against C1; no drift.
- Compatible with the operator's trading constraint: signal detection is universal, execution is Bitget-only.

## 3. Scope

### In scope
- Signals derived from any publicly-observable CEX product surface: Earn programs, Launchpools, staking, dual-currency, spot listings, futures listings, funding rates, open interest, order-book depth.
- Signals derived from cross-venue divergences (Bitget vs Binance vs Bybit, etc.) on same coins.
- Signals derived from on-chain observability layered on top of CEX events (whale wallet positioning, DEX-CEX flow imbalances).
- Any hypothesis operating under the shared discipline invariants below.

### Out of scope
- Signals requiring paid data services beyond current subscriptions (Nansen deep queries, CryptoRank API, Bloomberg terminals). Free-tier scraping of the same underlying data IS in scope.
- Signals from social/attention channels where the free-tier data is fundamentally broken (X/Twitter post-2023 API changes). Telegram and Discord are in scope.
- Trading venues other than Bitget for *execution*. Any coin considered for the study must be Bitget-tradable.

## 4. How hypotheses fit within this frame

Each hypothesis is a specific answer to "what publicly-observable signal exposes informed positioning?" Each is pre-registered as its own document + YAML spec, git-tagged at registration, timestamped on OSF.

**Currently registered hypotheses under FRAME_C1:**
- (pending) HYPOTHESIS_A2a — Bitget+Binance Earn sold-out predicts short-horizon returns (fixed-horizon labeler v0.2.1)
- (pending) HYPOTHESIS_A2b — same as A2a but with triple-barrier labeler v0.3.0
- (pre-committed for post-gate) HYPOTHESIS_A2c — event-study CAR labeler v0.4.0
- (pending, separate track) HYPOTHESIS_A3 — order-book depth impact around Earn events

Each hypothesis has its own gate criteria and decision date. Family-wise correction (Holm-Bonferroni) applies across all hypotheses registered under FRAME_C1, tracked in `KILL_COUNTER.md`.

## 5. Discipline invariants (non-negotiable)

These bind every hypothesis under FRAME_C1:

- **No feature/labeler iteration after seeing any label's return.** de Prado's Second Law.
- **All hypotheses pre-registered BEFORE code writes labels.** Registration = markdown narrative + YAML spec + git-tag + OSF timestamp.
- **Red-team section mandatory.** Every hypothesis must include "How this hypothesis would look real even if it isn't" — enumerate confounds and null-explanations before running.
- **Family-wise correction applies to every gate call.** KILL_COUNTER.md tracks the running test count; gate thresholds tighten automatically.
- **Purged K-Fold CV with embargo** (de Prado Ch 7) for any statistical claim on labeled time series.
- **Uniqueness-weighted effective n** deflates PSR before comparison to gate threshold.

## 6. Frame-level success and failure criteria

FRAME_C1 as a whole is judged by:

**Success**: at least one registered hypothesis passes its gate at the pre-registered decision date, with the pass surviving family-wise correction. → Move to out-of-sample replication phase.

**Failure**: all registered hypotheses fail their gates by 2026-12-31. → Frame is refuted at current sample sizes. Options: (a) declare the frame null and pivot to a different frame, (b) revise data collection strategy (larger universe, longer horizon) and re-register hypotheses freshly.

Frame is NOT judged on the outcome of any single hypothesis. Individual hypothesis failure is expected and informative; frame failure requires all hypotheses to fail together.

## 7. Amendment policy

- **Adding a hypothesis**: no amendment required. Register the new hypothesis under this frame, add it to KILL_COUNTER.md, done.
- **Removing scope**: allowed with a note in the amendment log below.
- **Broadening scope**: requires a new frame version (FRAME_C1.v2) and re-registration of all in-flight hypotheses under it.
- **Changing invariants**: not allowed while hypotheses are in flight. Would require a new frame entirely.

## 8. Amendment log

| Date | Amendment | Reason | Committed |
|---|---|---|---|
| 2026-07-28 | v1 initial registration | Decisions 1-6 locked in Session 3 | (pending) |
