# METHOD — confounds, statistical power, purged CV

## 1. Confound catalog

The Earn signal, if it exists, is entangled with several other forces that also drive small-cap price action. If we do not control for these at the label level or the analysis level, any correlation we find is uninterpretable.

### 1.1 Token generation event (TGE) proximity

**The problem.** Newly listed tokens on Bitget pump on listing day regardless of Earn. This is the strongest confound. If we do not exclude the first N days, any "Earn signal" is really just "new listing signal."

**The control.** Compute `bitget_listing_age_days` at anchor_ts. Split analysis into:
- `age < 7d` — excluded from primary claim
- `7d ≤ age < 30d` — reported separately (young listing regime)
- `age ≥ 30d` — primary claim

**Residual risk.** Even 30-day-old tokens on Bitget are usually 30-day-old tokens globally. The confound softens but does not disappear.

### 1.2 VC unlock cadence

**The problem.** Many post-TGE tokens have linear or cliff unlock schedules. A distribution to VCs at t+30d creates sell pressure independent of Earn. If Earn events happen to cluster near VC unlocks, we misattribute.

**The control.** Pull vest schedules from Token Terminal, TokenUnlocks.app, or the project's docs. Tag `known_vest_unlock_within_3d`. Report the correlation separately with and without unlock-adjacent events.

**Residual risk.** Vest schedule data is uneven quality. Many shitcoins do not publish, or publish inconsistently. Best effort.

### 1.3 KOL / paid promotion cycles

**The problem.** Coordinated promotion cycles create price movement not correlated with anything on-exchange. This is unobservable in structured public data.

**The control.** Use `perp_oi_pct_change_prior_24h` as a proxy for "someone is positioning." If OI ramped in the 24h before anchor, tag it. If Earn signal only shows up conditional on OI ramp, then the true signal is OI, not Earn.

**Residual risk.** OI proxy is noisy. Micro-caps have thin OI. False negatives likely.

### 1.4 Bitget listing selection bias

**The problem.** Bitget's listing team may only accept tokens with a certain profile (VC-backed, KOL-promoted, specific chain). If Earn is offered on a subset of listings, the "Earn-eligible" universe may already be a biased sample.

**The control.** Build a **control arm** of tokens listed on Bitget in the same time window that did NOT get an Earn program. Compare their post-listing behavior to the Earn cohort. Difference = Earn effect. Absence of difference = listing bias, no Earn effect.

**Residual risk.** Control arm may be very small if most new listings get Earn. In that case, the design cannot separate Earn from listing.

### 1.5 General shitcoin beta

**The problem.** Micro-cap tokens have high beta to TOTAL3 (total market cap ex-BTC-ex-ETH). If the overall shitcoin index dumps 20% during our observation window, any single-name dump is partly explained by beta.

**The control.** Report R after subtracting TOTAL3 beta or a shitcoin-specific index. Or: pair-match each Earn event with a same-day non-Earn control and report the difference-in-differences.

**Residual risk.** Beta estimation on newly listed thin-liquidity tokens is unreliable.

### 1.6 Regime effects

**The problem.** Bull markets pump everything. Bear markets dump everything. Earn signal may only work in one regime.

**The control.** Report label distribution stratified by BTC 30d realized volatility bucket and 30d return sign.

**Residual risk.** Regime buckets thin out the effective n. Minimum n per bucket for a claim = 20 per de Prado Ch 7.

### 1.7.1 Stale anchor from pre-existing sold-outs

**The problem.** For events that were already `sold_out=true` at the moment the scraper first observed them, `sold_out_first_seen_at` reflects "when we discovered it," not "when the pool actually saturated." The label window then measures residual price behavior N days AFTER discovery, not fresh reaction to saturation. This is a systematic bias that inflates the effective anchor-to-event lag by an unknown amount.

**The control.** Only events for which we recorded a status transition into 6 in `earn_events_status_log` are eligible for the primary label calc. Their anchor precision is ±scrape cadence (15 min). Every other sold-out event gets tagged `unlabelable_reason = "stale_anchor"` by the backfill script and is excluded from the primary corpus.

**Residual risk.** The first days of the pilot inherit a batch of already-sold-out pools that will never enter the primary corpus. Effective n at Phase 3 is the count of 2→6 transitions we witnessed live, not the count of sold-out rows in `earn_events`.

### 1.7 Look-ahead bias in APR field

**The problem.** APR may be adjusted by Bitget after pool close. If our scrape happens post-close, we might read a different APR than users saw at open.

**The control.** Scrape at high frequency during the announce → open window. Snapshot APR at open_ts + 1 minute. Never overwrite. Provenance capture required.

**Residual risk.** If we start scraper post-open on an already-open pool, that event is unusable and must be tagged as such.

## 2. Statistical power planning

### 2.1 Effect size assumption

Assume Earn signal produces an average edge of R = +0.30 (dump prediction correct on average, magnitude ~30% of ATR). This is a **plausible small-cap edge**, not a headline claim. Standard deviation of R across events estimated at σ = 1.5 based on general shitcoin volatility.

Standardized effect size Cohen's d ≈ 0.30 / 1.5 = 0.20 (small).

### 2.2 Sample size for detection

For a two-sided t-test at α = 0.05, power = 0.80, d = 0.20:

n ≈ 2 * ((z_α/2 + z_β) / d)² = 2 * (1.96 + 0.84)² / 0.04 ≈ 392

That is the raw sample size. **Effective sample size after uniqueness deflation is smaller.** de Prado's uniqueness weights typically produce effective_n ≈ 0.7 * raw_n on overlapping label windows, so we need raw_n ≈ 560.

**That is beyond our reach.** Bitget lists maybe 20 to 40 tokens per month with Earn programs. Half will fail confound filters. Realistic collection rate is 10 to 20 usable events per month.

### 2.3 Adjusted expectations

We will not reach the "detect a small effect at 80% power" threshold within any reasonable timeframe. Adjusted plan:

- **Phase 3 primary decision:** at n = 30 (six months), report PSR against SR* = 0. This is the go/no-go gate.
- **Phase 3 secondary:** at n = 100 (twelve months), report PSR against SR* = 0.5 and stratify by product type.
- **Phase 3 tertiary:** at n = 300 (thirty-six months), if we get there, run purged CV with 5 folds and embargo.

If the effect is real and large (R = +0.60, d = 0.40), 30 events is enough. If the effect is small (R = +0.15), we will never distinguish it from noise. **Accept this.** The Second Law says do not iterate the label window to force a large effect.

### 2.4 What "signal exists" looks like at n = 30

- Sign of mean R matches predicted sign for the sub-hypothesis
- PSR against SR* = 0 ≥ 0.95
- HHI concentration (Herfindahl on positive-R contributions) ≤ 0.15 — the edge is diversified across events, not driven by 1 or 2 outliers
- Median-to-mean ratio ≥ 0.5 — the mean is not distorted by fat tails
- Sign consistency across at least 2 of 3 confound splits (age, regime, control-arm)

All five must pass. If any one fails, halt. Do not iterate.

## 3. Purged K-Fold CV design

Implemented in `src/defi_investor/backtest/cv.py` from de Prado Ch 7. Purge + embargo primitives are standalone; `PurgedKFold` iterates contiguous test folds.

### 3.1 Label spans

Each event has `[anchor_ts, barrier_hit_ts]` as its label span. Multiple events on the same token can overlap. Multiple events on different tokens on the same day can overlap in time but not in symbol.

### 3.2 Purging rule

For a test fold defined by a time range [T_start, T_end]:
- Purge from training any event whose label span overlaps [T_start, T_end]
- Embargo: purge additionally any event whose anchor_ts is within `embargo_pct * total_span_days` of T_end

Recommended embargo_pct = 0.01 (de Prado Ch 7.4).

### 3.3 Fold count

At n = 30 primary decision point, use k = 3 folds. At n = 100, k = 5. Do not use k = 10 with n < 100 — folds get too thin.

### 3.4 Reporting per fold

- n_train, n_test
- Mean R on test fold
- PSR on test fold against SR* = 0
- Sign of edge

Fold-consistent sign is a stronger claim than pooled mean.

## 4. PSR and DSR

### 4.1 Probabilistic Sharpe Ratio

Per de Prado Ch 14.7.2:

PSR(SR*) = Φ((SR - SR*) * √(n - 1) / √(1 - γ₃*SR + (γ₄ - 1)/4 * SR²))

where γ₃ = skewness of returns, γ₄ = kurtosis. Implemented in `src/defi_investor/backtest/stats.py`.

### 4.2 Deflated Sharpe Ratio

We are NOT running multiple strategy candidates in parallel. This is one hypothesis. DSR (Ch 14.7.3) does not apply unless we start comparing sub-hypotheses (H1 vs H2 vs H3) and then only against the best-selected one. Skip DSR at n = 30. Reintroduce at n = 100 if we are comparing sub-hypotheses.

### 4.3 Reporting format

Every claim in a phase report includes:

```
Claim: PoolX APR ≥ 100% predicts dump R = +0.35 within 5 days
n_raw = 42, n_effective = 30.1 (after uniqueness deflation)
Mean R = +0.35, StDev R = 1.4, Sharpe = +0.25
Skewness = -0.4, Kurtosis = 3.1
PSR vs SR* = 0: 0.87
PSR vs SR* = 0.5: 0.02
HHI concentration = 0.09 (diversified)
Median R = +0.28 (mean-median ratio 0.80, healthy)
Confound splits:
  age ≥ 30d subset: n = 25, mean R = +0.38 (holds)
  low OI ramp subset: n = 22, mean R = +0.31 (holds)
  control-arm difference: +0.29 R (holds, effect not just listing bias)
```

Anything less than this is not a claim, it is a look.

## 5. What not to do

- **Do not** report annualized Sharpe without PSR.
- **Do not** iterate the label window after seeing a poor result.
- **Do not** merge sub-hypotheses into a "PoolX or Simple Earn Fixed" cohort to inflate n. Report separately.
- **Do not** exclude events post-hoc because they are inconvenient. Predefine exclusions in the labeler. Exclusion criteria go into the CHARTER, not the notebook.
- **Do not** run 20 versions of the labeler and report the best one. This is the exact backtest overfitting de Prado warns against.
- **Do not** call anything a signal until it passes the five gates in section 2.4.

## 6. What to do

- Commit the labeler code once. Version it. Any change requires a version bump and re-labeling the entire corpus from raw captures.
- Report at each n milestone (30, 100, 300). Do not report in between.
- Between milestones, work on scraper reliability, provenance, and confound tag quality. Not on the labels.
- If you find a bug in the labeler, fix it, bump version, re-run. Log the diff between versions. Do not silently update.
