# PLACEBO_A2b — Placebo cohort protocol for HYPOTHESIS_A2b

**Status:** DRAFT, pre-committed before any placebo backfill is run.
**Not a new hypothesis** — this is a robustness check on the A2b gate.
Does NOT add to `KILL_COUNTER.md` (would only add if this became a
distinct testable hypothesis, which it is not; it is a diagnostic).

**Purpose.** Distinguish "the Earn sold-out event is associated with
directional price movement" from "these coins have directional drift
regardless of Earn events." A2b's binomial test on `P(+1)` vs `P(-1)`
under symmetric barriers can be biased if the underlying coin population
has systematic drift (e.g. a bear-market coin selection). Running the
identical labeler on synthetic non-event anchors for the same coins
tells us the null-model distribution of the same statistic. Real split
vs placebo split side-by-side is the robustness diagnostic.

**Pre-committed BEFORE any placebo backfill fires**, so subsequent
placebo sampling cannot be tuned to shift the diagnostic outcome.

---

## Design

### Sampling protocol

For each real A2b sold-out event indexed by `(venue, product_id, coin_name, anchor_ts)`:

1. Draw `K = 20` synthetic anchor timestamps `t_placebo` for the same
   `coin_name`, satisfying all of:
   - `t_placebo` uniformly random in `[coin_first_bitget_candle + 30d, now - 168h - 1h]`
     (need ≥ 30d prior for `sigma_20d`, and ≥ 168h forward for the h=168 walk)
   - `|t_placebo - any_real_anchor| >= 168h` on the SAME coin (excludes contamination
     by any real event's forward-walk window)
   - `t_placebo not within 7d of TGE` (same `within_7d_of_tge` exclusion as A2b)

2. If fewer than K candidates survive exclusions, use all available. Never
   loosen the exclusion criteria to hit K. `K_effective` per coin logged.

3. Reproducibility: fixed seed `PLACEBO_SEED = 20260817`. Rerunning
   against the same corpus + same seed produces identical anchors.

### Labeler

Identical to v0.3.0 A2b: `k_upper = k_lower = 2.0`, `sigma_20d` on daily
log returns, horizons `(24, 48, 168)h`, Bitget candles as price source.

**Storage:** `labeler_version = "0.3.0-placebo#h{H}"` — distinct from real
A2b rows (`0.3.0#h{H}`) so `gate_report_a2b` never accidentally reads
placebos as real.

### Reporting

At A2b gate day (2026-09-30 or n≥30, whichever first), report side-by-side
per horizon:

```
Real A2b (h=168h): +1=A  -1=B  0=C  |  P(+1|dir) = A/(A+B)  binomial p = X
Placebo (h=168h): +1=A'  -1=B'  0=C' | P(+1|dir) = A'/(A'+B') binomial p = X'
Placebo 95% CI on P(+1|dir): [lo, hi] via percentile bootstrap
Real P(+1|dir) inside placebo CI? Y/N
```

**Interpretation rule (pre-committed):**
- If real `P(+1|dir)` falls OUTSIDE the placebo 95% CI in the same
  direction as the real split's lean: real effect is not fully explained
  by coin-level drift.
- If real `P(+1|dir)` falls INSIDE the placebo CI: coin-level drift is
  a candidate confound for the real split; A2b evidence is weakened.
- Inside/outside is a diagnostic aid, NOT a gate criterion. The primary
  gate remains the Holm-Bonferroni binomial p-value.

### Second-Law compliance

- Sampling protocol fixed here BEFORE any placebo backfill runs.
- Labeler unchanged (v0.3.0 spec is frozen).
- Exclusion windows fixed here; cannot be loosened after seeing results.
- If placebo split shows unexpected patterns, no code changes to the
  placebo protocol are permitted without amending this doc and re-running
  under the new protocol from scratch (with old placebo rows discarded).

### Kill counter

Placebo does not add to N_REGISTERED. Rationale: placebo is not a
separately-testable hypothesis with its own alpha; it is a
diagnostic-only tool applied to A2b's existing gate.

---

## Amendment log

| Date | Change | Reason |
|---|---|---|
| 2026-08-17 | Initial draft | Session 7 wrap. Sampling protocol, K, exclusion windows, and interpretation rule fixed. |
