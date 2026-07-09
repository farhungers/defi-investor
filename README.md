# defi-investor

Research project: does Bitget's Earn program predict pump-and-dump behavior of the underlying token?

## The hypothesis in one paragraph

Bitget offers Earn products (staking, PoolX, Simple Earn Fixed, Shark Fin) on selected tokens at APRs that occasionally reach 100 to 400 percent. High APR pools have a total pool size cap, a definite open time, and go "sold out" when demand exceeds cap. Observation on LABUSDT (365% APR, currently sold out) suggests these parameters may leak information about coordinated distribution: the exchange or issuer uses high APR to soak up float during the accumulation phase and releases distributions on a calendar that clusters with dumps. If true, the Earn schedule is a leading indicator observable from the public UI.

## The main questions

1. **Is there a correlation** between Earn pool events (open, sold out, distribution unlock) and downstream price action (dump R, time to top, drawdown depth)?
2. **Is it stationary** across product type (PoolX vs Simple Earn Fixed vs Shark Fin) and across time?
3. **Is it exploitable** after realistic frictions (spread, borrow rate, funding, exit liquidity on small caps)?
4. **Is it distinguishable** from confounds (TGE timing, VC unlocks, KOL promo cycles, general shitcoin beta)?

## Why this is not part of mm-radar

- **Clock.** mm-radar operates on 1H and 4H bars; Earn events are daily to weekly.
- **Universe.** mm-radar is USDT-M perp shitcoins; Earn covers spot-only tokens too.
- **Lifecycle.** mm-radar's `wick_watchlist` is entry-triggered on price; Earn is calendar-triggered on schedule.
- **Discipline hygiene.** mm-radar just adopted de Prado's discipline. Bolting on a hypothesis with a different clock and label geometry contaminates both.

## Current phase

**Phase 0: Investigation.** No code. No live data. Only the charter, schema design, method design, and case study. Read `docs/` in numeric order.

## Phase gates

- **Phase 1 (build):** scraper collecting live event catalog to Supabase. Success = 30 days of clean data, no gaps.
- **Phase 2 (label):** apply triple-barrier labels to at least 30 completed events. Success = labels reproducible from raw captures.
- **Phase 3 (measure):** report PSR + purged CV on the label set. Success = go/no-go decision on whether an edge exists.
- **Phase 4 (deploy):** only if Phase 3 passes at PSR ≥ 0.95, ship a live alerter. Not before.

## Kill criteria

See `docs/CHARTER.md` for the full list. Short version: if scraper cannot be built stably, if events are too rare (n < 30 in 6 months), if confounds cannot be controlled, or if Phase 3 fails PSR gate, project halts.

## Not a trading bot

No live positions. No auto-execution. This is a research instrument. If Phase 3 succeeds, Phase 4 emits alerts only. Any execution layer is a separate project.
