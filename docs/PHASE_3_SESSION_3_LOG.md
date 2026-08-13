# Phase 3 Session 3 log — 2026-08-13 (Kepler, Session 6)

**Session start state:** `main` at `456b12a` (Session 5 wrap). 304/304 tests. Phase 3c LIVE, Phase 3d LIVE (18 A2b labels), Phase 3e READY FOR VM DEPLOY (Migration 010 applied). Working tree clean.

**Session end state:** `main` unchanged locally (pending push greenlight). Working-tree diff: 2 modified + 1 new file (local hardening + cleanup workflow). 305/305 tests. VM launch of `capture_daemon` still pending user action.

**Session goal (user framing):** analyze current performance, then elevate logic + accuracy. Bounded by the Second Law: no iteration on the `{+1: 3, -1: 1, 0: 14}` A2b split, no A3 numeric interpretation.

---

## Performance read-out at session start

- **A2b:** 18 labels from 6 events. Directional n=4. Gate threshold n≥30 or 2026-09-30. Not touched.
- **A3:** 0 rows. `capture_daemon` not yet on the VM; the single biggest accuracy multiplier is turning it on.
- **Corpus:** hourly Bitget + Binance scrape still running; sold-out events accrue toward n≥30 in the background.
- **Codebase:** 304/304 green, `main` clean at `456b12a`.
- **Latent-bug audit (fresh, via Explore subagent):** no new instances of the two known bug classes (suffix-blind equality, cap-before-filter). Two real weak spots surfaced:
  1. `BatchedL2Writer` drop-oldest tested in isolation only — drain-loop interaction was never exercised. Exactly the shape of a silent-in-prod bug that would burn Supabase quota.
  2. `gate_report_a2b.py:60` used `.eq("labeler_version", "0.3.0#hH")`. Works today, but the same *class* as the `_already_labeled` bug we just fixed. Backfill code uses `.like()`; gate did not.

---

## What shipped (local, not yet committed)

### `tests/test_orderbook_storage.py` — new test `test_drop_oldest_survives_active_drain`

Runs the writer with `queue_max=5, batch_size=2, max_interval_s=0.05`, bursts 50 enqueues (guarantees drops), sleeps to let the drain make several passes, bursts 5 more (proves the loop is still live), then stops. Asserts:
- `dropped > 0` (backpressure actually fired)
- `enqueued == 55` (ledger complete)
- `flushed == enqueued - dropped` (no snapshots stuck)
- `queue_depth == 0` (final drain worked)
- Row count in the fake client matches `flushed`

Would catch: condition-event not re-arming after a drop, drain-loop spin, silent snapshot loss.

### `scripts/gate_report_a2b.py` — `.like()` hardening

Changed `_load_labels_for_horizon`:
```python
# before
r = sb.table("earn_event_labels").select("*").eq("labeler_version", version_suffix).execute()
# after
r = sb.table("earn_event_labels").select("*").like("labeler_version", f"{version_prefix}%").execute()
```

`h24` vs `h240` collision is theoretical (horizons are pre-committed constants `24/48/168`). Defense-in-depth: mirrors the `.like()` pattern in `backfill_labels_v030._already_labeled`. No behavior change on today's data.

**Verified `gate_report.py` (A2a) and `gate_report_a3.py` do NOT have the same shape** — both use one-row-per-event without the horizon-suffix trick, so `.eq()` is correct there.

### `.github/workflows/orderbook_cleanup.yml` — free-tier pg_cron substitute

New workflow, hourly cron at `:17`, runs `scripts/cleanup_orderbook_snapshots.py --retain-hours 24`. Isolated job (own concurrency group), 5-min timeout. This is what the design doc has been calling out as required before the daemon lands data — 500 MB free tier + no pruning = quota blown in days at 5-symbol pilot rate.

**Not yet fired** — will fire on first push + hourly thereafter. First real burn happens once the daemon starts writing.

---

## What I did NOT do (Second-Law fence, explicit for the record)

- Did NOT tune `k` in the triple-barrier labeler despite the 14 no-hits dominating the split.
- Did NOT re-score A2b horizons.
- Did NOT add or change any A2b/A3 feature.
- Did NOT run `gate_report_a2b.py` (n=6, gate is pre-committed).
- Did NOT interpret any A3 numbers (there are none anyway — `orderbook_features` is empty).
- Did NOT push to origin.

---

## What next session picks up

1. **Launch `capture_daemon` on the VM** (blocking on user action from this session — command below). 5-symbol pilot:
   ```
   python -m defi_investor.orderbook.capture_daemon --venues bitget,binance --max-symbols 5
   ```
   Watch for `l2 writer stats:` lines in the daemon log and rows appearing in `orderbook_snapshots_l2`.

2. **Verify orderbook_cleanup workflow fired** — check GH Actions tab after the first `:17` after push. First real burn happens on the hour after daemon writes land.

3. **Smoke `gate_report_a3.py`** once any snapshots exist. Should render the "insufficient data" path cleanly. **Do not interpret the numbers.**

4. **Storage-quota decision before scaling past ~10 symbols** — design doc estimates 10 GB/day raw at 50 symbols vs 500 MB free tier.

---

## gh-auth check

Ran `gh auth status` at session open. Drifted to `arbabfar` again. Recovered with `gh auth switch -u farhungers && gh auth setup-git`. Memory rule earned its keep on first invocation, again.
