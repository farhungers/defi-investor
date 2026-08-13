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

Ran `gh auth status` at session open. Drifted to `arbabfar`. Recovered with `gh auth switch -u farhungers && gh auth setup-git`. **Drifted a second time mid-session** on the `test_cards.py` push (both remotes returned "Repository not found"). Same recovery. Something in a parallel Claude session flips the active account; the memory rule earns its keep every time.

---

## Session 6 second half (post-VM-launch-block)

The plan closed with items 3+4 (drain test + gate suffix) shipped, cleanup workflow wired, session wrap committed and pushed at `2f391ff`. Then user asked to continue while waiting on VM launch.

### `1260960` — test_cards.py simplification

User flagged `tests/test_cards.py` as feeling too long (168 lines). Refactored to 144 lines (-14%):
- Single `_ev(**kwargs)` factory replaces two hardcoded `_lab()`/`_usdt()` ctors.
- `OBSERVED_AT` module constant collapses 8 repeated timestamp literals.
- `_assert_contains(text, *fragments)` helper names the missing fragment on failure instead of pointing at an anonymous `assert X in c`.
- Merged the two cohort with/without tests into one that exercises both sides.
- 11 tests → 10. Assertion coverage preserved. 304/304 (was 305; one test net dropped by the cohort merge).

Honest note in the closing message: the LOC cut was modest because I chose to preserve all assertion fragments and one-test-per-concern for the other cases. Could go more aggressive with `pytest.parametrize` but at the cost of failure locality.

### `c88c7ee` — coverage_forecast.py

New read-only script. Answers one question: given the historical rate of labelable sold-outs, are we on track to hit n≥30 by 2026-09-30 (48.5 days out)?

Live run against prod:
- **17 sold-outs** (10 Bitget + 7 Binance). Binance's first sold-out landed 2026-07-30, so we now have ~14 days of dual-venue history.
- Projected n at gate by rate window:
  - 7d rate (Binance-dominant): n=58.6 (on track)
  - 14d rate: n=41.3 (on track)
  - 30d rate: n=29.9 (marginal, short by 0.1)
  - 60d rate: n=30.8 (marginal)
  - 90d rate (pre-Binance baseline): n=26.2 (short by 3.8)

**Discipline-critical caveat baked into the script:** these are *event ceilings*. The A2b gate needs *directional* n≥30 per horizon. Session 5 showed 4/6 events resolved directional but extrapolating that ratio from n=6 is Second-Law territory, so the script only forecasts raw event counts and flags that directional-n ≤ event-n.

**What this does NOT change:** the 5-symbol VM daemon pilot is A3-scope only. A2b coverage grows via the hourly Earn scraper (already running in GH Actions), not L2 capture. So the forecast doesn't argue for scaling the daemon early.

### Second latent-bug audit (L2 pipeline, unattended-runtime focus)

Ran an Explore audit over `bitget_l2`, `binance_l2`, `capture_daemon`, `universe`, `storage`, `features` specifically for bugs that would surface only after hours/days of unattended runtime. Five findings; verified each against source:

1. **Bitget subscribe ACK not validated** — real, but loud symptom (0 enqueues in writer stats within 30s). Not silent.
2. **Binance timestamp reuse across rows** — **FALSE POSITIVE.** `_parse_depth5_payload` yields exactly one snapshot per message; no loop over rows. Both `received_at` and `exchange_ts_ms` deriving from same `now` is intentional (Binance doesn't ship server ts on depth5, per module docstring).
3. **Flush error suppression** — overstated. `_n_flush_errors` counter exists and emits every 30s in periodic stats.
4. **Drain-loop condition race** — real but bounded by `max_interval_s=2s` timeout. Symptom is latency not data loss. Irrelevant for 5-min A3 windows.
5. **Universe fetched once at startup** — real, deferred. Not an issue for a 5-symbol pilot; matters at multi-week full-universe scale.

**Decision: no code changes.** Discipline says don't add complexity beyond what the task requires. All findings are working-as-designed, loud-symptom, or deferred-scope. If daemon shows any symptom in the wild, we fix then with real evidence.

### VM launch — deferred by user (2026-08-13)

Walked user through the 8-step VM launch sequence (SSH, clone/pull, venv, .env transfer, dry-run, tmux, verify). User said the walkthrough felt confusing and asked me to explain what was actually happening. Re-explained in plain language: research is running itself via hourly scraper (A2b), VM is only needed for A3, and there's no fire.

User picked **option 1: skip A3 for now.** A3 gate is pre-committed to 2026-11-30 (later than A2b's 2026-09-30) so the deferral has room. A2b is unaffected.

**Memory updates (persisted, no commits):**
- `reference_user_has_vm.md` — added a "Current status" header noting the deferral. Behavioral guidance: do NOT open `gm` with "let's launch the daemon"; do NOT propose VM setup as a next-session action unless user brings it up; if user asks about A3, remind them the daemon needs to run to accrue data and ask whether they want to launch now or keep deferring.
- `MEMORY.md` — index one-liner updated to match.

---

## Session end state (revised)

- Commits this session (in order): `2f391ff` (hardening + cleanup workflow), `1260960` (test_cards refactor), `c88c7ee` (coverage forecast). All pushed to origin + backup.
- 304/304 tests green.
- Working tree clean.
- A2b: 17 sold-outs, ceiling projections marginal-to-comfortable depending on which rate window you trust.
- A3: 0 rows. VM daemon setup deferred by user. Hourly `orderbook_cleanup` workflow armed and will fire on `:17`, but does nothing until snapshots exist.
- Two memory files updated.

## What next session picks up

Nothing pending from this session. The corpus grows quietly via the hourly scraper. Next session opens as a normal `gm` with agenda proposals based on whatever the user brings; do not lead with the VM daemon.
