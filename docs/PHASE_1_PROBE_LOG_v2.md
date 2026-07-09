# PHASE_1_PROBE_LOG_v2 — product detail + tier probe

**Author:** Vault (Session 2, 2026-07-10)
**Task:** Task 8 investigation per `PHASE_1_EXECUTION_PLAN.md` §B4.
**Goal:** find total pool size and per-tier APR breakdowns that aren't on the main earning page.
**Result:** total pool size is NOT publicly exposed; per-tier APR IS available and we're currently discarding it.

## What I tried

### 1. `savings-details?id=<productId>` variants — all 404

Tried 10 URL patterns (`asia/earning/savings-details`, `en/earn/savings-details`, `/earning/details?id=&type=Savings`, `/simple-earn/*`, etc.). Every variant returns Bitget's `/404` page for both a sold-out product (`LAB`, `1438002720001814528`) and an active one (`DATA`, `1450321820050079744`). Raw captures in `data/raw/probe_v2/lab_savings_details.html`.

### 2. Main earning page hrefs — no per-product routes

The `/asia/earning` list page contains only family-level hrefs: `/asia/earning/savings`, `/dual-investment`, `/shark-fin`, `/smart-trend`. No product-detail links. This means Bitget's UI opens product details as a modal/panel client-side, not as a routed page. No SSR to scrape.

### 3. Savings family landing page `/asia/earning/savings` — richer per-product schema

Page returns 200 with a `__NEXT_DATA__` blob containing `pageProps.data` = 348 wrapped coin rows. Each row nests `bizLineProductList[].productList[]` with fields NOT present on `/asia/earning`:

- `originalMaxApy` / `originalMinApy` — pre-boost APR (the current `maxApy` is often the boosted "activity" APR)
- `defaultCheckedCreateTime` — epoch ms creation time for the DEFAULT tier
- `activeProduct` bool
- `annualizedRateType`, `productLevel`, `productLevelGroup`, `stickType` — categorization we can use for cohorting
- `settleCoinId` / `settleCoinName` / `settleCoinImgUrl` — reward-coin metadata

Raw capture: `data/raw/probe_v2/savings_landing.html`.

### 4. Pool total size — still NOT present anywhere in SSR

Searched the savings-landing JSON for `totalPool`, `totalAmount`, `totalStake`, `totalQuota`, `poolSize`, `capacity`, `currentAmount`, `subscribeAmount`, `totalIssue`, `totalLimit`, `remainingQuota`, `availableAmount`. Only match was in help text: "product subscription limit − subscribed amount". So Bitget's UI DOES surface a "remaining quota" bar, but the numbers come from an authenticated API, not SSR. Confirms Session 1's finding.

**Kill-clause invoked (per plan §B4):** "if Bitget rate-limits or blocks the detail-page fetches, back off to list-page-only. Not fatal for H3 hypothesis." — the failure mode here is worse than rate-limit: the data simply isn't public. Same effect.

### 5. Per-tier APR structure — IS available on the main list page, and we're throwing it away

Distribution of `apyList` tier count across the 399 products on the last scrape:

| tiers | count |
|------:|------:|
|     0 |    33 |
|     1 |   359 |
|     2 |     8 |
|     3 |     2 |

**33 products with empty apyList** — very likely sold-out or paused (worth confirming by joining to `status`). **359 single-tier** — the LAB-style bait cohort. **8 two-tier / 2 three-tier** — classic stablecoin ladders. Example USDT ladder:

```
tier 0: 6.16% APR on the first 300 USDT
tier 1: 1.50% APR on the next 120 million USDT
```

Current parser flattens all tiers to a single `max_apy` / `min_apy`. For USDT that means we store `min_apy = 1.50, max_apy = 6.16` — the tier structure (where the break is, how deep the ladder goes) is discarded.

## What this means for the pilot

**For the H3 hypothesis** (Earn parameters correlate with underlying pump-and-dump): tier structure is a first-class feature. A single-tier 365% Savings product is not the same instrument as a two-tier stablecoin ladder. Losing tier info makes cohorting weaker in Phase 2.

**For pool size**: unrecoverable from public data. Options for Phase 2+:
1. Use `maxStepValue * unknown_N` as a proxy — not usable
2. Log in to Bitget as a research account, hit the authed API — violates the "no-account" scope of Phase 1
3. Infer pool size from status transitions (time-to-sold-out × APR × per-user cap) — indirect but grounded

## Proposed action (needs user sign-off)

Add a `tiers JSONB DEFAULT '[]'::jsonb` column to `earn_events` and extend the parser to store the full `apyList` verbatim per product. Zero risk to existing rows (nullable column, no backfill needed — the next scrape will populate). Also add the enriched savings-landing fields (`originalMaxApy`, `defaultCheckedCreateTime`, `stickType`) as their own columns.

**Why now vs later:** the 30-day pilot burns clock the moment the VM starts. Every day of pilot data captured under the current schema is a day of tier information lost. Fixing now costs one small migration; fixing later costs a re-scrape of everything, which we can't do because Bitget's list is a live snapshot.

**Kill:** if the migration breaks anything on Supabase, roll back and stay on the current schema. Not fatal.

## What did NOT ship

- Actual schema change and parser update. Waiting on your call.
- Fetching an authenticated Bitget account. Out of Phase 1 scope.

— Vault, Session 2 mid-flight
