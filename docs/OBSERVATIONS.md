# Observations — surprising things worth remembering

Per `docs/ROADMAP_V2.md` §Observation log. Everything surprising gets written here so the roadmap can be revised based on evidence. Second Law binds: observations DO NOT drive design changes on the current experiment.

## 2026-07-28 — descriptive characterization of the current sold-out corpus (Kepler)

**Setup.** After Session 3 shipped Phase 3c/3d/3e code, ran a one-shot descriptive script against the live Supabase to characterize what's actually in `earn_events` where `sold_out=True` and what labels exist in `earn_event_labels` for `labeler_version='0.2.1'`. Purpose: understand the corpus, NOT to iterate on labeler design.

**Numbers.**

- **8 sold-out events total** across both venues (7 Bitget + 1 Binance — the Binance one landed today via the new scraper).
- **6 of 8 events share the identical anchor timestamp `2026-07-09T18:52:43`.** These were sold_out at the very first scrape of Phase 2 (2026-07-09 was the day the Phase 2 labeler backfill started). Their `sold_out_first_seen_at` is therefore not the true saturation time — it's the first moment we observed them.
- Only 2 events have anchors reflecting actual 2→6 transitions: ONDO (2026-07-27) and BABY (2026-07-28).
- APY spread on sold-out events: 0.3% to 52.0% (heterogeneous — from stablecoin ladder to high-APY bait pool).
- Product types: 7 Bitget `Savings` + 1 Binance `LENDING_FLEXIBLE`. No other biz lines have sold out yet.

**v0.2.1 label rows (37):**

- **1 resolved label** (SKYAI, `T1_UP` hit → realized_r ≈ -1.0 under H1=dump convention, meaning the price PUMPED after sold-out; hypothesis wrong for this event).
- 19 rows excluded as `stale_anchor` — the six 2026-07-09 events × ~3 backfill iterations each.
- 16 rows excluded as `horizon_not_yet_resolved` — recent events whose 7-day window hasn't closed yet.
- 1 excluded as `no_candles_available` (Bitget doesn't trade the coin).

**Confound tag coverage on v0.2.1 labels:**

| Tag | Populated / total |
|---|---|
| `bitget_listing_age_days` | 17/37 (46%) |
| `within_7d_of_tge` | 17/37 (46%) |
| `btc_ret_7d_prior` | 18/37 (49%) |
| `btc_30d_realized_vol` | 8/37 (22%) |
| `btc_ret_30d_prior` | 8/37 (22%) |
| `perp_oi_pct_change_prior_24h` | 2/37 (5%) |
| `known_vest_unlock_within_3d` | 0/37 |

**Surprises.**

1. **Stale-anchor exclusion is eating 75% of the sold-out corpus.** 6 of 8 events (all pre-Phase-2-scraper-start) are dropped from primary because their observed sold-out time is unreliable. Effective primary-universe size for A2a today is n=2 (ONDO + BABY). To reach the n≥30 gate at the current organic transition rate (~1 event / 10 days observed), we'd need ~10 months. This is much slower than the "Realistic ETA 2-4 weeks" note in the outdated CLAUDE.md.

2. **Zero vest-unlock coverage on labels.** `known_vest_unlock_within_3d` is null on every row. Two possible causes: (a) the tokenomist.ai SSR scraper isn't populating `earn_next_unlocks` yet (per PHASE_2_SESSION_2_LOG, 5-10% coverage was expected — 0% is worse), or (b) the confound-attach step in `backfill_labels.py` isn't reading from `earn_next_unlocks` correctly. Worth investigating.

3. **Perp OI coverage at 5%** is expected — need 24h of prior snapshots for the confound to be computable. Migration 005 applied ~2026-07-10, snapshots at `*/15` since. So 5% is oddly low for a corpus that's been building for 20 days.

4. **The one resolved label (SKYAI) shows `label = -1`** (T1_UP hit, realized_r ≈ -1). Under H1's "dump" sub-hypothesis this is EVIDENCE AGAINST. n=1 is not a signal — noted for completeness only; Second Law forbids acting on it.

**Implications — logged, NOT acted on.**

- Corpus growth rate is the throttle. Multi-venue expansion (Phase 3c LIVE now) should help; expect Binance to contribute events at some rate — measurement needs 2-4 weeks of data.
- The stale-anchor filter is doing its job (protecting anchor precision) but at massive corpus cost. **A future post-gate revision** might introduce a "probabilistic anchor" label that treats early-observed events with a wider anchor uncertainty band rather than binary exclusion. NOT changing anything now.
- Vest-unlock coverage at 0% needs a separate investigation, but that's confound instrumentation, not labeler design — safe to touch without Second Law violation.

**What this session did NOT do:**
- Did not run the v0.3.0 backfill.
- Did not change the labeler.
- Did not adjust `stale_anchor` filter thresholds.
- Did not touch A2a gate criteria.

All noted for the roadmap's weekly self-check; the vest-unlock zero-coverage is worth a separate diagnostic pass.

## 2026-07-28 — A3 label-mapping sign bug caught by integration test (Kepler)

**Setup.** Writing an end-to-end integration test for the A3 pipeline (synthetic L2 snapshots → `compute_depth_asymmetry_5min` → label decision). Test forced me to trace signs end-to-end for the first time.

**Bug.** `backfill_labels_a3._label_from_asymmetry` used the mapping:
```python
if asymmetry >= theta:  return +1
if asymmetry <= -theta: return -1
```

But the pre-registered formula `(log(ask_pre)-log(ask_pre_pre)) - (log(bid_pre)-log(bid_pre_pre))` produces a NEGATIVE value when the ASK side contracts (first term becomes negative, second term stays at zero). So the code was labelling ask contractions as `-1` and bid contractions as `+1` — the OPPOSITE of what HYPOTHESIS_A3.md says (`+1 if ask-side contraction ≥ theta_asym`).

**Impact if not caught.** No A3 labels have been written yet (Migration 010 unapplied, capture_daemon undeployed), so the bug is fixed before any real label rows exist — this is a code correction, NOT a pre-registration violation. Had the bug shipped and produced label rows, any positive gate result (`E[R|+1] > E[R|-1]`) would have been interpreted as the wrong direction of the hypothesis.

**Fix.** Inverted the label mapping in `_label_from_asymmetry`:
```python
if asymmetry <= -theta:  return +1   # ask contraction
if asymmetry >= +theta:  return -1   # bid contraction
```
Same fix mirrored in the integration test's local helper. Docstring on the fixed function explains the sign relationship so future readers don't fall into the same trap.

**Broader lesson.** Sign-convention bugs in pre-registered hypotheses are especially dangerous because the wrong sign LOOKS RIGHT to statistical machinery — the gate would fire on the same-magnitude but wrong-direction effect. Integration tests that thread synthetic data through the whole pipeline are cheap insurance against this class of bug.

**Roadmap implication.** Add sign-convention integration tests as a checklist item for any future hypothesis whose label semantics involve a directional feature. Not urgent — currently only A3 has this structure.

## 2026-07-28 — vest-unlock coverage bug root-caused and fixed (Kepler)

**Setup.** OBSERVATIONS entry earlier today flagged `known_vest_unlock_within_3d` as 0/37 populated. Diagnosed today.

**Two bugs, one silent failure mode.**

1. **Alphabetical truncation.** `vest_snapshot_universe` had a hard cap `_MAX_COINS_PER_RUN = 300` and processed coins in whatever order the caller passed them. `scraper.py` passed `sorted({...})` — pure alphabetical. Universe grew to 541 coins, so 241 coins beyond rank 300 (letter 'M' onward, roughly) were NEVER snapshotted. Five of eight sold-out coins (ONDO, PREOPAI, SKYAI, SNEK, W) were in that dead zone.

2. **Job timeout.** In production the full pipeline (Bitget scrape + Binance scrape + OI snapshot for 877 combined-catalog coins + vest snapshot for 300 coins + listings) exceeds the 5-minute GH Actions job timeout. Many runs cancel around 5m30s. When cancellation hits inside the vest step, its writes are lost silently.

3. **Combined effect.** `earn_next_unlocks` was empty in production — zero rows across all statuses — before today. Even the alphabetically-early coins that would have been in the 300-cap weren't getting snapshotted because the job was cancelling before the vest step completed.

**Fixes.**
- `vest_snapshot_universe` gained a `prior_last_seen` optional kwarg. When provided, coins are ordered NEVER-SEEN first, then OLDEST-SEEN first. Rotation gives full universe coverage over successive runs even under the cap. 3 new tests.
- `scraper.py` looks up `earn_next_unlocks` and constructs `prior_last_seen` before each run.
- One-shot manual population: ran `snapshot_universe` locally for the 8 sold-out coins. 7 rows written, 2 of which have real next-unlock dates (ONDO 2027-01-18, W 2026-08-07).

**Not fixed in this iteration:**
- The 5-minute job-timeout root cause (too many steps in one job). Actually a bigger problem — even with rotation, if the vest step doesn't complete in the budget, no writes land. Follow-up: consider splitting vest to its own workflow file with its own external cron trigger. Requires user to add a second cron-job.org entry. Deferred.

**Update, later same day.** Bumped `scrape.yml` `timeout-minutes` from 5 → 10 as the minimal effective fix. Worst-case current pipeline is ~7 min; new margin is ~3 min. Splitting vest to its own workflow remains available as a long-term option if the universe grows past what 10 min can cover.

## 2026-07-28 — v0.3.0 backfill: 0 labels, 21 rows all unlabelable (Kepler)

**Setup.** Ran `scripts/backfill_labels_v030.py` live against production for the first time. 8 sold-out events (7 Bitget + 1 Binance); 2 skipped as `stale_anchor` (per METHOD §5.1), 7 processed → 21 rows written (× 3 horizons per event).

**Result.** All 21 rows have `unlabelable_reason` set. Two failure modes:

- **9 rows / 3 events: `no_daily_candles`.** Coins `preOPAI`, `FUEL`, `PREOPAI` etc. return empty results for both perp (`USDT-FUTURES/candles`) and spot (`/spot/market/candles`) endpoints. Likely delisted from Bitget after listing on Earn — Earn products can outlive spot listings, especially for very-low-cap/promo tokens. Or the coin never had a Bitget market to begin with (Earn program without exchange listing).

- **12 rows / 4 events: `anchor_before_first_walk_bar`.** Coins have daily candles (sigma_20d computable) but the 1-minute walk fetch does NOT return bars extending back to the anchor. Anchors are 2026-07-09 (18+ days old); **Bitget's public 1-minute klines endpoint appears to have limited retention** — empirically returns bars only for a recent window (needs measurement; probably 7-30 days, but the API doesn't document this cleanly).

**Implications.**

- A2b's primary universe is effectively **forward-looking only** for the 1m-walk path. Events with sold-out anchors from before Bitget's 1m retention horizon (~7-30 days?) cannot be labeled retrospectively. Combined with the stale-anchor filter (which already dropped 6/8 events), the effective retrospective corpus for A2b is 0.
- **Not a code bug** — the labeler correctly detects the missing data and marks it unlabelable rather than fabricating a label. This is the pre-registered exclusion behavior.
- **Not a pre-registration violation** — A2b spec says "Price source: Bitget spot 1m klines" and does not commit to any retention window. Missing data → excluded from primary. Working as designed.

**What this doesn't reveal.** Whether the 1m retention is truly the barrier vs some other API quirk (paginated fetch stopping early, symbol mapping wrong, etc.). A dedicated diagnostic script could measure Bitget's actual 1m retention empirically — but Second-Law-adjacent, since it would inform whether to relax the spec. Deferred.

**Non-implications.**

- Does NOT block the A2b gate call — events sold-out AFTER today, if scraped and labeled promptly (within ~7 days while 1m data is available), will populate the primary universe normally.
- Does NOT weaken A2a (fixed-horizon v0.2.1 uses 4H bars which have longer retention; 1 resolved v0.2.1 label already exists for SKYAI).

**Roadmap addition.** Add empirical Bitget 1m/4H retention measurement as a Phase 3-adjacent diagnostic. Also add a proactive "backfill within X days of sold-out" cadence check to `backfill_labels_v030.py` so we don't lose events by delay.
- Existing v0.2.1 label rows won't retrospectively get `known_vest_unlock_within_3d` populated. Would need a manual UPDATE against Supabase, but with only 1 resolved label in the batch this doesn't materially move the gate.

**Systematic lesson.** Confound-instrumentation bugs are silent by nature: `NULL` on a confound column just means "not evaluated." Whenever we add a confound to the labeler, we should also add a coverage-monitoring assertion (e.g. "at least X% of resolved primary labels have this confound populated") so a broken data-collection pipeline shows up loudly.
