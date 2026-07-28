# Order-book capture (Phase 3e / HYPOTHESIS_A3) — design

This is the design doc for the L2 order-book capture pipeline that
HYPOTHESIS_A3 depends on. A3 is a **forward-looking** hypothesis: it
requires L2 depth snapshots covering the 5 minutes preceding each
sold-out event. Free-tier Bitget/Binance WebSocket streams provide only
live data (no historical replay), so we can only label events that
happen AFTER capture starts.

## Deploy model

Different from the rest of the project. Bitget/Binance L2 WS feeds are
persistent connections; GitHub Actions cron (5-min timeout, re-runs)
cannot host them. Three options for the persistent runner:

| Option | Cost | Complexity | Notes |
|---|---|---|---|
| A. User's own always-on machine | $0 | Low | Runs when the user's PC is on. Coverage gaps when PC sleeps. |
| B. Free-tier cloud (Fly.io, Railway, Render, Deno Deploy) | $0-5/mo | Medium | Usually enough headroom for a single WS process. Free tier subject to changes. |
| C. Dedicated VPS (Hetzner CX11, Vultr, DigitalOcean) | $4-6/mo | Medium | Reliable; user greenlight needed for paid resource. |

**Recommendation:** Option A for prototype (validate the pipeline works
end-to-end), then move to Option B or C before A3's gate date
(2026-11-30) to eliminate coverage gaps.

## Storage volume

- Bitget spot `books5` channel pushes every 100ms per symbol.
- If we track 50 coins (universe = coins with active Bitget Earn), that's
  50 × 10 pushes/sec = **500 snapshots/sec = 43M/day**.
- Payload per snapshot ~250B → ~10 GB/day raw.
- Retention TTL: A3 only needs the 5-minute pre-event window per sold-out
  event. That's < 1% of raw data. So: **rolling 24h raw + permanent
  rolled-up features** for each observed sold-out event.

## Universe scoping

Full-universe (all Bitget spot) is impractical for free-tier. Scope to:

1. Coins with an active Bitget Earn product (~150 coins as of 2026-07)
2. Plus coins that recently HAD an Earn product (past 30d)
3. Prune when a coin drops from both criteria for 30d

Refresh this universe daily from `earn_events` and `bitget_listings`.

## Data model

New table `orderbook_snapshots_l2`:
```
inst_id      TEXT NOT NULL
venue        TEXT NOT NULL           -- 'bitget' | 'binance'
received_at  TIMESTAMPTZ NOT NULL    -- our wall clock
exchange_ts  TIMESTAMPTZ NOT NULL    -- server-side (Bitget: ts field)
bids         JSONB NOT NULL          -- [[price, size], ...] top-5
asks         JSONB NOT NULL
PRIMARY KEY (venue, inst_id, exchange_ts)
```

Rolled-up feature table `orderbook_features` (populated by the labeler
at label-time, so the raw table can be pruned):
```
venue         TEXT NOT NULL
product_id    TEXT NOT NULL
anchor_ts     TIMESTAMPTZ NOT NULL
depth_asymmetry_5min  NUMERIC
ws_gap_max_s          NUMERIC      -- max gap in the pre-window (exclusion signal)
n_snapshots_used      INTEGER
PRIMARY KEY (venue, product_id, anchor_ts)
```

## Feature computation (per A3 spec)

`depth_asymmetry_5min` for one event, per HYPOTHESIS_A3.md §Labeler spec:

1. Fetch all L2 snapshots for the coin in
   `[anchor - 10min, anchor - 5min]` (pre-pre window) and
   `[anchor - 5min, anchor]` (pre window).
2. For each snapshot, compute `depth_ask_top5 = sum(size for price, size in asks[:5])`
   and same for bids.
3. Average over each window: `depth_ask_pre_pre`, `depth_ask_pre`, same for bid.
4. `asym = (log(depth_ask_pre) - log(depth_ask_pre_pre)) - (log(depth_bid_pre) - log(depth_bid_pre_pre))`
5. Label: `+1` if `asym >= theta_asym` (ask-side contracted), `-1` if
   `asym <= -theta_asym` (bid-side contracted), `0` otherwise.
6. `theta_asym = 0.5` (pre-committed).

Exclusion: if the largest gap between consecutive snapshots in either
window exceeds 60s, mark unlabelable with reason `ws_gap_over_60s_in_pre_window`.

## Build plan

- [x] `src/defi_investor/orderbook/bitget_l2.py` — WS client prototype (subscribes to books5, prints to stdout). Locally runnable today.
- [ ] `websockets` dependency in `pyproject.toml` (currently ambient in dev env)
- [ ] `binance_l2.py` — same shape, wss://stream.binance.com:9443/ws
- [ ] Storage layer: async batched inserts to Supabase, backpressure-aware
- [ ] Universe manager: refreshes tracked coin list daily from `earn_events`
- [ ] Migration 010: `orderbook_snapshots_l2` + `orderbook_features`
- [ ] Feature extractor: computes depth_asymmetry_5min for an event
- [ ] A3 backfill: mirrors backfill_labels_v030 for A3 events
- [ ] A3 gate report: mirrors gate_report_a2b (t-test, not binomial, per A3 spec)
- [ ] Retention: nightly `DELETE FROM orderbook_snapshots_l2 WHERE received_at < now() - interval '24 hours'` — but ONLY after event backfill has run for the window

## Testing

- Locally: run `python -m defi_investor.orderbook.bitget_l2 BTCUSDT ETHUSDT` and confirm live snapshot prints in stdout for several minutes.
- Reconnect: kill wifi for 5 seconds, verify auto-reconnect + backoff resets.
- Feature: unit test `depth_asymmetry_5min` on synthetic snapshots with known contraction magnitudes.

## Open questions for user

1. Deploy target (Option A / B / C)?
2. Willing to run the WS client on local machine for a few days as
   prototype validation before committing to cloud?
3. Any preference on cloud provider if we go B/C?
