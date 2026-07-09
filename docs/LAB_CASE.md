# LAB_CASE — the motivating example

The user surfaced this hypothesis after observing LABUSDT on Bitget Earn: 365% APR, sold out, alongside a pump-and-dump pattern on the perp market.

This case study is **not evidence for the hypothesis.** It is one anecdote, and one anecdote does not establish anything. The purpose of documenting it here is to (a) make sure the successor AI understands the shape of the observation the user is trying to systematize, and (b) provide a concrete example to test the scraper and labeler against once Phase 1 ships.

## What we observed (user report, 2026-07-09)

- LABUSDT trades on Bitget as both spot and USDT-M perp
- Bitget Earn currently lists LAB at 365% APR
- The LAB Earn pool is "sold out": no more capacity for new deposits
- The user's read: high APR + sold out is temporally correlated with a pump-and-dump pattern visible on the LAB chart

## What we do NOT know yet

- What Earn product type LAB is in (PoolX? Simple Earn Fixed?)
- When the LAB pool opened
- When it sold out
- Total pool size in LAB terms and in USDT terms
- Distribution schedule (continuous vs cliff)
- Term days (if Fixed)
- Whether LAB had a Bitget listing that predated the Earn program by ≥ 30 days
- Whether other tokens with similar Earn parameters showed the same dump pattern

Every one of those unknowns is a scraper Phase 1 task. Until we have those data points on 30+ tokens, LAB is one candle we cannot even fully characterize.

## What the LAB case tests in Phase 1

Once the scraper is live, run these as smoke tests:

1. **Backfill probe.** Can we retrieve LAB's Earn pool params from any endpoint at all after the fact? If yes, we can build a limited historical spot-check. If no, LAB itself is only usable as forward-tracking.
2. **Perp candle sidecar.** Pull LAB perp candles from Bitget for `[first_seen_ts - 7d, first_seen_ts + 21d]`. Confirm candle availability, granularity, and no gaps.
3. **Confound tags.** For LAB, compute:
   - `bitget_listing_age_days` at the anchor
   - `total3_pct_change_7d` around the anchor
   - `perp_oi_pct_change_prior_24h`
   - `known_vest_unlock_within_3d` (best-effort from token docs)
4. **Sign check.** If LAB does dump after the pool sold out, the H1 (soaking) sub-hypothesis is directionally consistent with one data point. This is a check-of-plumbing, not a claim.

## The trap to avoid

The strongest cognitive risk in a hypothesis started from one anecdote is **anchoring on the anecdote**. If LAB dumps hard, the analyst will want to define "success" as "predicts a LAB-like dump." That is the exact backtest overfitting trap.

The label design in `DATA_MODEL.md` is intentionally symmetric (upper and lower barriers, three-value label) and predefined before we have Phase 1 data. Do not adjust the label geometry to make LAB look better in retrospect.

The Second Law: **do not research under the influence of a backtest.** LAB is a backtest of one. Its result does not adjust the labeler.

## What to do if LAB pumps instead of dumps

Log it. Do not re-hypothesize on the spot. n = 1. The correct action at n = 1 is to keep collecting.

## Successor AI briefing

If you are picking this up in Phase 1:

1. Do not spend more than 30 minutes trying to reconstruct LAB's historical Earn params from Wayback Machine or other archives. The archives are not reliable enough to bear a research claim.
2. Do get LAB's Bitget listing_ts, first perp candle, and current price action, because those are cheap to fetch and will be useful smoke-test data for the scraper regardless of hypothesis.
3. Do treat LAB as an ordinary event in the corpus once its Earn pool ends. No special weight, no special exclusion.
