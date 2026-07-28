# Phase 3e — running the L2 capture daemon on your local machine

For prototype validation. Once we confirm the pipeline works end-to-end
against real data for a week, we can move to a paid VPS for the pre-gate
run (2026-09-30 → 2026-11-30). See `docs/ORDERBOOK_DESIGN.md` for the
full deploy tradeoffs.

## Prerequisites

1. **Apply Migration 010 to Supabase.** The capture_daemon writes to
   `orderbook_snapshots_l2` which doesn't exist yet. Open Supabase SQL
   editor and paste `db/migrations/010_orderbook.sql`. Same flow as the
   Migration 009 walkthrough — should take ~30 seconds.

2. **Confirm `.env` has creds.** The daemon needs `SUPABASE_URL` and
   `SUPABASE_SERVICE_ROLE_KEY`. Both are already in your `.env`.

3. **Ensure the Python env is ready.** `websockets>=13.0` was added to
   `pyproject.toml` in Phase 3e. If you haven't reinstalled since,
   run `pip install -e .` once.

## Quick start (dry run — no DB writes)

```
python -m defi_investor.orderbook.capture_daemon --dry-run --max-symbols 5
```

Expected: connects to Bitget and Binance WS, subscribes to the 5
alphabetically-first coins in the universe (0G, 1000CAT, etc.), streams
~10 snapshots/sec each, logs periodic stats every 60s. Ctrl-C to exit
(the async writer drains its queue cleanly on shutdown).

## Full local run (writes to Supabase)

```
python -m defi_investor.orderbook.capture_daemon
```

Full 541-coin universe on both venues. Bitget partitions into 14
subscription batches (40 symbols/batch); Binance opens 4 WS connections
(150 streams/URL cap).

**Expected snapshot volume:** ~500 snapshots/second/venue × 2 venues =
1000/sec = 3.6M/hour = 86M/day. At ~250 bytes each ≈ **22 GB/day raw**.
Supabase free tier is 500 MB, so this exceeds free storage within an
hour. Two mitigations:

1. **Run with `--max-symbols 50`** to restrict to the alphabetically-first
   50 coins. ~2 GB/day, still manageable on free tier for a few days.
2. **Enable the retention pg_cron** noted in Migration 010's comments
   (nightly `DELETE FROM orderbook_snapshots_l2 WHERE received_at < now() - interval '24 hours'`).
   Requires Supabase Pro tier or a pg_cron alternative — not yet set up.

**Kepler recommendation for prototype week:** run with `--max-symbols 50`
and no retention. Rotate the 50 coins to prioritize sold-out-likely
candidates (high APR, low cap). Costs ~14 GB total for a 7-day test.

## Backgrounding

**Windows (native):**
```
Start-Process -WindowStyle Hidden python -ArgumentList "-m","defi_investor.orderbook.capture_daemon","--max-symbols","50"
```

**Windows (Git Bash / WSL):**
```
nohup python -m defi_investor.orderbook.capture_daemon --max-symbols 50 > data/raw/daemon.log 2>&1 &
```

Verify it's running:
```
ps -ef | grep capture_daemon    # unix-like
Get-Process -Name python | Where-Object CommandLine -Like "*capture_daemon*"    # PowerShell
```

## Auto-restart on machine boot (optional)

Skip for prototype week — a `nohup` in a terminal you leave open is
sufficient. Do this only if you decide to commit to local hosting
past the validation window.

**Windows Task Scheduler:** create a task triggered on user logon that
runs the same command above.

## Monitoring what the daemon is doing

Live queries against Supabase:

```
# Rows per hour, last 6 hours
SELECT date_trunc('hour', received_at) AS hour, COUNT(*)
FROM orderbook_snapshots_l2
WHERE received_at > now() - interval '6 hours'
GROUP BY 1 ORDER BY 1 DESC;

# Coverage per symbol
SELECT venue, inst_id, COUNT(*), MAX(received_at) - MIN(received_at) AS span
FROM orderbook_snapshots_l2
WHERE received_at > now() - interval '1 hour'
GROUP BY 1, 2 ORDER BY 3 DESC LIMIT 20;
```

If a symbol has zero rows: probably a coin-name mismatch. Check
`venue_coin_map` and consider adding a manual override.

## Stopping the daemon cleanly

`Ctrl-C` (or `kill <PID>` from another terminal). The writer's `stop()`
method drains its queue before exiting (up to 10 seconds). No data loss.

## Once we have 24 hours of L2 data

Run the A3 backfill (this will only work for events sold-out AFTER the
daemon started — retrospective labeling requires historical L2 which we
don't have):

```
python scripts/backfill_labels_a3.py
```

Then the gate report:
```
python scripts/gate_report_a3.py
```

Both are read-only against `orderbook_features`. Both will show
`descriptive-only` until an event actually sells out and we have ≥10
minutes of pre-event L2 data for its coin.

## Escalation path

- **Daemon crashes repeatedly:** check `data/raw/daemon.log` — likely
  a WS reconnect issue. Bitget and Binance both have exponential
  backoff already; sustained crashes suggest an API surface change.
- **Supabase write errors:** may indicate Migration 010 not applied,
  or free-tier row-count cap hit. Query the table row count first.
- **Universe explosion:** if the earn_events catalog grows past ~1000
  coins the batching will need more parallelism. Not urgent under
  current growth rate.

## When to move to cloud

Move to a paid VPS (Option C in `docs/ORDERBOOK_DESIGN.md`) when either:
- Your machine's coverage gaps (sleep, restarts) cause A3 events to
  fall in dark windows more than once a week.
- The pre-gate window (2026-09-30 → 2026-11-30) is 2 months out or
  closer, at which point cloud uptime becomes hypothesis-critical.
