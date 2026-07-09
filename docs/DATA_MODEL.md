# DATA_MODEL — Bitget Earn taxonomy, event schema, label design

## 1. Bitget Earn product taxonomy

> **Updated 2026-07-09 (Vault, Phase 1 Task 1) after empirical probe.** The original taxonomy in this file was a priori. Bitget's actual `secondBizLine` labels are what appear on the wire. See `PHASE_1_PROBE_LOG.md` for the corrected mapping. Original narrative retained for reasoning, but implementations must use the wire labels below.

**Wire `secondBizLine` values observed:** `Savings`, `PosStaking`, `SharkFin`, `CashPlus`, `FundMarket`, `Trend` (Dual Investment). No `PoolX` on the main Earn page (lives on `/earning/launchpool`, client-rendered, deferred).

**Primary universe for Phase 1:** `Savings` with `maxApy >= 50` and status ∈ {2, 6}. This is the LAB-shaped cohort: high APR, new-listing, sold-out is observable. All 18 in-flight ≥ 50% pools as of 2026-07-09 are `Savings`.

### 1.1 PoolX (highest signal expectation)

- **Mechanic:** Users stake BGB (Bitget's platform token) into a pool. The pool distributes a **fixed total amount** of a **newly listed token** over a defined duration (typically 3 to 14 days). Each BGB-hour of stake earns a proportional share.
- **Timing markers:** announce_ts, open_ts, sold_out_ts (if applicable), close_ts, distribution_ts (may be continuous or lump).
- **Why signal is expected:** PoolX is often the **primary distribution channel** for a new listing. Token supply enters user hands via PoolX and is unlocked to spot immediately. Users can dump on unlock. High APR reflects thin free float; sold-out reflects demand saturation.
- **Expected sign:** dump R positive (price falls) in the window from distribution_ts + 0 to + 5 days.

### 1.2 Simple Earn Flexible

- **Mechanic:** User deposits token, withdraws anytime, earns a floating APR set by Bitget.
- **Timing markers:** APR changes (Bitget adjusts based on demand). No open/close.
- **Why signal is expected:** APR spikes may indicate Bitget lending demand shift (short pressure) or token float management. Weak signal.
- **Expected sign:** weak, needs empirical test.

### 1.3 Simple Earn Fixed

- **Mechanic:** User deposits token, locks for a fixed term (7 / 15 / 30 / 60 / 90 days), earns a fixed APR. High APR pools cap total deposit.
- **Timing markers:** open_ts, sold_out_ts, term_end_ts (unlock).
- **Why signal is expected:** **Locks reduce sell pressure during term.** May be neutral or bullish during lock. Distribution at term_end may cluster with sell pressure. The LAB observation (365% APR sold out) is likely this product family.
- **Expected sign:** neutral during lock, dump R positive in the window from term_end_ts + 0 to + 3 days.

### 1.4 Shark Fin

- **Mechanic:** Structured derivative product. Payoff depends on whether price stays in a range. Bitget hedges the exposure.
- **Timing markers:** subscription window, observation period, settlement.
- **Why signal is expected:** Bitget's hedging flow may create range-bound price behavior during observation. Not a distribution signal.
- **Expected sign:** volatility compression during observation. Not primary hypothesis.

### 1.5 Dual Investment

- **Mechanic:** User picks a strike and expiry, deposits either the base or quote token, earns a fixed yield. If strike is breached, user receives the other token.
- **Timing markers:** subscription window, expiry.
- **Why signal is expected:** Similar to Shark Fin. Bitget delta-hedges. Not primary hypothesis.
- **Expected sign:** weak.

### 1.6 On-chain Earn

- **Mechanic:** Bitget routes user deposits to external DeFi protocols (Aave, Compound, Lido).
- **Why signal is expected:** None. Signal source is external protocol economics, not Bitget. Out of scope.
- **Expected sign:** N/A. Exclude.

## 2. Priority for Phase 1

Focus scraper on **PoolX** and **Simple Earn Fixed high-APR pools** (defined as APR ≥ 50%). These have the strongest theoretical signal and the highest visibility on the UI. Add Simple Earn Flexible and Shark Fin in Phase 2 if Phase 1 catalog is sparse.

## 3. Event schema

One row per Earn pool. Store as JSONL for provenance, mirror to Supabase for queryable state.

```json
{
  "event_id": "poolx_LAB_2026-07-01",
  "product_type": "poolx | simple_flex | simple_fixed | shark_fin | dual_inv",
  "underlying_symbol": "LABUSDT",
  "underlying_chain": "bnb | eth | sol | ...",
  "announce_ts": "2026-07-01T08:00:00Z",
  "open_ts": "2026-07-02T08:00:00Z",
  "sold_out_ts": "2026-07-02T08:03:12Z",
  "close_ts": "2026-07-05T08:00:00Z",
  "first_distribution_ts": "2026-07-02T08:00:00Z",
  "last_distribution_ts": "2026-07-05T08:00:00Z",
  "term_days": 3,
  "apr_at_open": 365.0,
  "apr_at_close": 365.0,
  "pool_size_underlying": 1000000.0,
  "pool_size_usdt_at_open": 4500.0,
  "sold_out": true,
  "min_stake": 1.0,
  "max_stake_per_user": null,
  "perp_available": true,
  "perp_symbol": "LABUSDT",
  "spot_available": true,
  "raw_capture_sha256": "abc123...",
  "raw_capture_path": "data/raw/2026-07-01/poolx_LAB_08-00-00.html",
  "collected_at": "2026-07-01T08:00:15Z",
  "scraper_version": "0.1.0"
}
```

Notes on fields:
- `pool_size_usdt_at_open` = `pool_size_underlying * spot_price_at_open`. Store both, compute at parse time.
- `min_stake` and `max_stake_per_user` are in BGB for PoolX, in the underlying for Simple Earn.
- `perp_available` gates whether this event is even eligible for the "trade the dump" hypothesis. Some tokens are spot-only.
- `raw_capture_sha256` is the hash of the raw HTML or JSON response the parser used. If parser changes, all events must re-parse from the same raw and produce the same output (unit-testable).

## 4. Price sidecar

For each event, at label time, join to a **price context table** keyed by `(symbol, ts)`:

```json
{
  "symbol": "LABUSDT",
  "market": "perp | spot",
  "candles_1h": [
    {"ts": "2026-07-02T08:00:00Z", "o": 0.0045, "h": 0.0048, "l": 0.0044, "c": 0.0047, "v": 12000}
  ]
}
```

Fetched from Bitget public candles. Cache per event, do not refetch. Provenance = capture timestamp + endpoint URL.

Window to cache per event: `[open_ts - 7d, close_ts + 21d]`. This covers all triple-barrier horizons.

## 5. Label design (triple-barrier applied to Earn events)

Per de Prado Ch 3.4, adapted to Earn events.

### 5.1 Anchor timestamp

For PoolX and Simple Earn Fixed, anchor = `first_distribution_ts` (the first moment token supply enters user hands).

For Simple Earn Flexible, anchor = `apr_spike_ts` (defined as APR crossing 50% from below).

For Shark Fin, anchor = `subscription_close_ts`. Not primary.

### 5.2 Three barriers

- **Upper barrier (T1_UP):** price rises `k_up * ATR(4h, 24)` above anchor close. Default `k_up = 2.0`. Hitting T1_UP means the token pumped, hypothesis wrong.
- **Lower barrier (T1_DOWN):** price falls `k_down * ATR(4h, 24)` below anchor close. Default `k_down = 2.0`. Hitting T1_DOWN means the token dumped, hypothesis right (if sub-hypothesis predicted dump).
- **Vertical barrier (T2):** time expires without either horizontal barrier hitting. Default `T2 = 7 days` for PoolX (short-lived distribution), `T2 = term_days + 3` for Simple Earn Fixed.

### 5.3 Primary label

Three-value label: `+1` (dumped, T1_DOWN hit first), `-1` (pumped, T1_UP hit first), `0` (T2 hit first, no decisive move).

Sign convention: `+1` = hypothesis correct for the H1 (soaking) sub-hypothesis. Adjust sign if sub-hypothesis predicts a pump instead.

### 5.4 Secondary label (for meta-labeling later)

Realized R at barrier hit or T2 close:

```
R = (P_hit - P_anchor) / (k * ATR) * -sign_of_prediction
```

Positive R = hypothesis correct in magnitude. Negative R = hypothesis wrong.

### 5.5 Uniqueness weights

Multiple Earn events on the same token within a T2 window overlap. Apply de Prado Ch 4.4 uniqueness weights. Port `_avg_uniqueness` from `mm-radar/src/mm_radar/post_mortem.py`. Effective n on the corpus is what feeds the PSR calculation.

## 6. Confound-control tags per event

Each event row gets a set of boolean tags computed at label time:

- `within_7d_of_tge` — first tradable candle of the token was within 7 days of anchor_ts
- `known_vest_unlock_within_3d` — public vest schedule (Token Terminal, docs) shows an unlock in the ±3d window around anchor_ts
- `total3_pct_change_7d` — total 3 market cap 7-day percent change (macro control)
- `perp_oi_pct_change_prior_24h` — proxy for KOL / coordinated positioning
- `bitget_listing_age_days` — days since first Bitget candle

Rows with `within_7d_of_tge = true` are excluded from the primary PSR calc but reported separately. TGE-day pumps are their own regime.

## 7. Supabase schema (target)

```sql
CREATE TABLE earn_events (
    event_id TEXT PRIMARY KEY,
    product_type TEXT NOT NULL,
    underlying_symbol TEXT NOT NULL,
    announce_ts TIMESTAMPTZ,
    open_ts TIMESTAMPTZ NOT NULL,
    sold_out_ts TIMESTAMPTZ,
    close_ts TIMESTAMPTZ,
    first_distribution_ts TIMESTAMPTZ,
    apr_at_open NUMERIC,
    pool_size_usdt_at_open NUMERIC,
    sold_out BOOLEAN,
    perp_available BOOLEAN,
    raw_capture_sha256 TEXT,
    collected_at TIMESTAMPTZ,
    -- label fields, filled by labeler
    label INTEGER,             -- +1, -1, 0, or NULL if not yet labeled
    realized_r NUMERIC,
    barrier_hit TEXT,          -- 'T1_UP', 'T1_DOWN', 'T2', or NULL
    barrier_hit_ts TIMESTAMPTZ,
    avg_uniqueness NUMERIC,    -- de Prado Ch 4.4
    -- confound tags
    within_7d_of_tge BOOLEAN,
    known_vest_unlock_within_3d BOOLEAN,
    total3_pct_change_7d NUMERIC,
    perp_oi_pct_change_prior_24h NUMERIC,
    bitget_listing_age_days INTEGER
);

CREATE INDEX earn_events_open_ts_idx ON earn_events(open_ts);
CREATE INDEX earn_events_symbol_ts_idx ON earn_events(underlying_symbol, open_ts);
```

Do not create this table until Phase 1 is greenlit and the scraper is ready to write.

## 8. Provenance guarantee

For any published claim ("PoolX events with APR ≥ 100% dump R +0.4 within 3 days, n=45"), the analyst must be able to:

1. Query the `earn_events` table by the same filter
2. Recover each event_id
3. Pull `raw_capture_path` and reparse
4. Recompute label from cached candles
5. Match

If any step fails, the claim is not publishable.

de Prado Ch 2: garbage data > no data > backtested-garbage data. Provenance is not optional.
