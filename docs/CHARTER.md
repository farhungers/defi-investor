# CHARTER — defi-investor investigation

**Author:** Vault seeded 2026-07-09; Kepler continuing from Phase 3
**Current phase:** 3 sub-phases 3c/3d/3e all shipped code (2026-07-28). Phase 3c LIVE (multi-venue capture); Phase 3d code-complete (v0.3.0 labeler + backfill + A2b gate + Holm-Bonferroni); Phase 3e code-surface-complete (L2 pipeline: WS clients + storage + universe + capture daemon + A3 backfill + A3 gate).
**Next phase gate:** Phase 3f — gate call on 2026-09-30 or n≥30 primary universe (per ROADMAP_V2.md), whichever first. FRAME_C1 pre-registered; A2a/A2b/A3 hypothesis docs + YAMLs + git tags (`prereg-*-v1`) + OSF timestamps (node `98kez`) in place. Kill-counter divisor `N=3` (A2c queued post-gate).

## 1. Hypothesis

Bitget Earn program parameters (product type, APR, pool size, open time, sold-out time, distribution schedule) are correlated with future price action of the underlying token. Specifically, three sub-hypotheses:

- **H1 (soaking).** Very high APR pools with small caps are a distribution vehicle. The pool sells out because the price implied by APR is above the market's fair value for the underlying. The token dumps within N days of the pool close or first distribution.
- **H2 (unlock cliff).** Distribution unlock timestamps cluster with local price tops. Distribution creates sell pressure regardless of exchange intent.
- **H3 (announcement window).** The window between pool announcement and pool open contains front-run price behavior on the perp market that predicts the direction after pool close.

## 2. Scope

**In scope:**
- Bitget Earn products, all product types (PoolX, Simple Earn Flexible, Simple Earn Fixed, Shark Fin, Dual Investment, On-chain Earn)
- **Binance Simple Earn products** (added 2026-07-28 in Phase 3c per Decision 1: multi-venue detection universe, Bitget-tradable filter). Both Bitget and Binance events count as "primary" if the underlying coin is Bitget-tradable.
- Tokens listed on Bitget perp or spot at any point during the observation window
- Correlation studies, not causation
- Public data only (no privileged sources, no insider info)
- L2 order-book snapshots for informed-positioning signal per HYPOTHESIS_A3

**Out of scope:**
- Other venues' Earn products beyond Bitget and Binance (OKX Earn, Bybit Earn). Cross-exchange comparison would require another expansion decision.
- Non-Earn Bitget promotions (Launchpad, airdrops, referral rewards)
- On-chain analysis of token contract (LP unlocks, dev wallet moves). Different data stack. Different project.
- Execution / trade automation. Alerts only if Phase 3 gate passes.

**Superseded by pre-registration:** The informal H1/H2/H3 sub-hypotheses below are the original Phase 1 framing. The Phase 3 gate operates on the formal `FRAME_C1` frame + `A2a` / `A2b` / `A3` hypothesis docs in `docs/preregistrations/`. H1 corresponds most closely to `A2a` (fixed-horizon return on sold-out anchor). H2 (unlock cliff) has an infrastructure hook via `earn_next_unlocks` but no formal pre-registration yet. H3 (announcement window) is not currently pre-registered.

## 3. Kill criteria (any one halts the project)

1. **Scraper cannot be built stably.** If Bitget UI/API blocks or rate-limits research-scale scraping such that we cannot maintain a 24/7 catalog with < 5% missing events over 30 days, halt.
2. **Event rarity.** If fewer than 30 completed Earn events (labelable to outcome) occur within 6 months of scraper going live, halt. This is de Prado's minimum for a purged CV claim.
3. **Confound explosion.** If in Phase 2 we cannot separate Earn signal from TGE cadence and VC unlock cadence using observable controls, halt. Confounded correlations are worse than no data.
4. **Statistical failure.** If Phase 3 PSR against SR* = 0 is below 0.95, halt. Do not iterate.
5. **Second Law violation.** If we catch ourselves refining the label window or the APR threshold after seeing a Phase 3 result, halt. Take a 2-week cooldown before revisiting.
6. **User pulls the plug.** Always.

## 4. Phase gates

| Phase | Deliverable | Success | Kill |
|---|---|---|---|
| 0 | Charter + schema + method + LAB case study | User reads and approves | User rejects hypothesis |
| 1 | Live scraper writing events to Supabase | 30d uptime, < 5% missing events | Bitget blocks or format churn beyond fix |
| 2 | Label pipeline producing triple-barrier labels | 30 labeled events, reproducible from raw | Cannot separate confounds |
| 3 | Statistical report: PSR + purged CV | PSR ≥ 0.95 on primary label | PSR < 0.95 — halt, do not iterate |
| 4 | Alerter (Telegram + Supabase) | User signs off on 10 live alerts | Any of above |
| 5 | Cross-exchange extension | Deferred |

## 5. Discipline rules (inherited from de Prado, adapted from mm-radar)

- **Features before backtest.** No optimization on labels that do not yet exist.
- **Second Law: do not research under the influence of a backtest.** Phase 3 result is one-shot. If it fails, halt.
- **Uniqueness weights.** For overlapping label windows (Earn events on the same token within a window), compute `avg_uniqueness` per de Prado Ch 4.4. Effective n < raw n.
- **Purged CV with embargo.** Do not train and test on adjacent time windows without a gap. Implemented in `src/defi_investor/backtest/cv.py` from de Prado Ch 7.
- **PSR gate.** Report PSR against SR* = 0 and against SR* = 0.5. Do not report annualized Sharpe without PSR.
- **HHI concentration.** If the edge concentrates on 1 or 2 outlier events, kill it. Diversified edges only.
- **Purged corpus.** Persist events to Supabase, not JSONL, so the catalog survives.

## 6. Data provenance

Every event row must be reproducible from raw captures. Store:
- Timestamped HTML / JSON capture from Bitget in `data/raw/YYYY-MM-DD/`
- Parsed event JSON in `data/events/YYYY-MM.jsonl`
- SHA256 of raw capture on the event row so re-parsing is possible

If provenance breaks, the event is dropped from the catalog. This is not optional. de Prado Ch 2.

## 7. Confounds we know about at seeding (see METHOD.md for full list)

- **TGE clustering.** New listings pump on listing day regardless of Earn. Control: exclude first 7 days after TGE from label windows.
- **VC unlock cadence.** Many new tokens have monthly linear vests. Control: pull vest schedule from Token Terminal or the token's docs.
- **KOL promo cycles.** Some tokens pump on paid promotion. Not observable directly; use aggregate perp OI change as a proxy for "someone is coordinating."
- **Bitget listing bias.** Bitget's listing team may only accept tokens with a certain profile. Control: control-arm on tokens listed but WITHOUT Earn program.
- **General shitcoin beta.** Micro-cap beta to TOTAL3 dominates single-name variance. Control: report R after subtracting TOTAL3 beta or a shitcoin ETF proxy.

## 8. Deliverables at end of Phase 0

- `README.md`
- `CLAUDE.md` (handoff)
- `docs/CHARTER.md` (this file)
- `docs/DATA_MODEL.md`
- `docs/METHOD.md`
- `docs/SCRAPER.md`
- `docs/LAB_CASE.md`
- `docs/ROADMAP.md`

Once these exist and the user approves, Phase 1 begins.

## 9. Open questions the seeding session did not resolve

These are handoffs to the Phase 1 AI or to the user.

1. **Does Bitget publish an Earn events API?** Seeding session did not verify. First Phase 1 task is to check Bitget's API docs for `/api/v2/earn/*` endpoints. If yes, use API. If no, DOM scrape.
2. **What is the exact PoolX product mechanic?** Users stake BGB to mine new tokens. Distribution is over the pool duration, not lump sum at close. This changes the "distribution timestamp" definition.
3. **Are Simple Earn Fixed pools relevant?** They lock user funds so users cannot dump. Might be neutral or negative signal (no sell pressure). Investigate in Phase 2.
4. **What is Bitget's ToS on scraping?** User should be aware if there is risk to account.
5. **Historical events.** No public archive. Phase 1 catalog starts from t0 = scraper go-live. Do not attempt to backfill from Wayback unless the user explicitly authorizes the time investment.

## 10. Governance

- User is the sole decision-maker on phase gates.
- AI (Vault, or successors) can make micro-decisions within a phase but must not skip a gate.
- If a kill criterion trips, AI halts and reports. Does not attempt a workaround without user approval.
