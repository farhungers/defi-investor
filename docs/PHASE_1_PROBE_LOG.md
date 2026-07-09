# PHASE_1_PROBE_LOG — Bitget Earn endpoint probes

**Run date:** 2026-07-09
**Operator:** Vault (Phase 1 kickoff)
**Deliverable status:** Task 1 complete. API path decided.

## 1. Public REST API probes (Earn)

Every documented `/api/v2/earn/*` endpoint I probed was either 404 or 400 (auth required). None expose Earn product listings publicly.

| Endpoint | HTTP | Notes |
|---|---|---|
| `GET /api/v2/earn/savings/product?filter=available` | 400 | `Invalid ACCESS_KEY`. Requires signed request. Not usable for scraping. |
| `GET /api/v2/earn/savings/coin-info` | 404 | Not found. |
| `GET /api/v2/earn/loan/public/coin-info` | 404 | Not found. |
| `GET /api/v2/earn/pool-x/product-list` | 404 | Not found. |
| `GET /api/v2/earn/pool/product-list` | 404 | Not found. |
| `GET /api/v2/earn/product/list` | 404 | Not found. |
| `GET /api/v2/earn/pool-x/list` | 404 | Not found. |
| `GET /api/v2/earn/product-list` | 404 | Not found. |
| `GET /api/v2/earn/simple/product` | 404 | Not found. |
| `GET /api/v2/asset/earn/product` | 404 | Not found. |
| `GET /api/v2/public/earn/product` | 404 | Not found. |
| `GET /api/v2/public/earn/pool-x` | 404 | Not found. |
| `GET /api/v2/spot/public/coins` | 200 | Sanity check that Bitget public API is reachable. |

**Decision:** REST API for Earn is user-account-only. Cannot be used for public catalog collection.

## 2. Web SSR probe (winning path)

`GET https://www.bitget.com/asia/earning` returns 200 with a full Next.js server-rendered HTML page containing a `<script id="__NEXT_DATA__" type="application/json">` blob with the complete Earn catalog embedded.

- **Size**: ~1.1 MB HTML, ~720 KB JSON blob inside
- **Auth**: none (public page)
- **Content**: server-side rendered product catalog at request time
- **Freshness**: catalog reflects live Bitget state (LAB status = 6 which matches user-reported "sold out")

### 2.1 pageProps structure

`data.props.pageProps` contains:

| Key | Type | Content |
|---|---|---|
| `hotData` | list[10] | Featured / highlighted products for the landing page |
| `listData` | list[348] | Complete catalog, grouped by coin |
| `structuralList` | list[3] | Structured products (SharkFin, Dual Investment "Trend", another Dual family) |
| `seoInfo` | dict | Page SEO metadata (ignore) |
| `bannerData` | * | Promotional banners (ignore) |

### 2.2 listData row shape

Each row is a coin. `coin_row.bizLineProductList` is a list of product groups by product family (`secondBizLine`). Each group has a `productList` of individual pool products.

```
listData[i] = {
  coinName, coinId, coinImgUrl, secondBizLine (aggregate label),
  bizLineProductList: [
    {
      secondBizLine, riskType, productLevel,
      productList: [
        { productId (as `id`), status, startTime,
          maxApy, minApy, apyList, period, periodType, lockModel,
          coinName, secondBizLine, apyType, activeProduct, ... }
      ]
    }
  ]
}
```

## 3. Product taxonomy (actual, not the CHARTER guess)

The CHARTER pre-committed to six product families based on a priori knowledge. Reality is different. Here are the actual `secondBizLine` values observed on live scrape 2026-07-09:

| secondBizLine | Product count | What it is |
|---|---|---|
| `Savings` | 368 | Flexible + fixed savings. **LAB and every high-APR pool are here.** |
| `PosStaking` | 28 | Proof-of-stake / launchpool staking (ETH, TON, DOT, and so on) |
| `SharkFin` | 3 | Structured range-bound derivative (in `structuralList`, keyed by underlying) |
| `CashPlus` | 2 | USDT and USDC flexible savings, low APY |
| `FundMarket` | 1 | Money-market-like product, one coin |
| `Trend` | (in structuralList) | Dual Investment (strike-based, `productTrend` field) |

**Correction to DATA_MODEL.md**: the taxonomy in `docs/DATA_MODEL.md` section 1 uses labels like "PoolX", "Simple Earn Flexible", "Simple Earn Fixed" that do not map 1:1 to Bitget's `secondBizLine`. See DATA_MODEL update in this session.

**PoolX-like (BGB staking → new tokens) is NOT on this page.** It lives at `https://www.bitget.com/asia/earning/launchpool` which is a client-side rendered shell (no SSR data). Out of scope for Phase 1. If Phase 2 needs it, we build a separate scraper against the launchpool endpoint.

## 4. Status code enum (observed)

From 402 products in the current listData:

| status | Count | Inference |
|---|---|---|
| 2 | 378 | Active / purchasable |
| 6 | 21 | Sold out (LAB has status=6 and user reports sold-out) |
| 4 | 3 | Deprecated / paused (one is PAXG from 2025-11) |

Additional evidence: `structuralList` products have an explicit `soldOut: bool` field. On `listData` rows, `soldOut` is inferred via `status == 6`.

**We will treat `status == 6` as `sold_out = true` and log status raw for provenance.** If a new status code appears, log an alert.

## 5. LAB case verification

The motivating case study is real and observable:

```
coinName: LAB
secondBizLine: Savings
productId: 1438002720001814528
maxApy / minApy: 365.00 / 365.00
startTime: 2026-05-12T07:54:45.770Z
status: 6 (sold out)
apyList: [{ apy: 365.00, minStepValue: 0, maxStepValue: 1000 }]
```

Interpretation:
- LAB Savings pool went live 2026-05-12
- APR is a flat 365% up to a per-user cap of 1000 LAB
- Currently sold out
- The scrape happened on 2026-07-09, so LAB has been in sold-out state for at least some time; we do not know the exact `sold_out_ts` from this one snapshot. Getting it requires periodic scraping and detecting the status transition.

## 6. "365% APR" is a template, not a per-token calibration

Three separate pools (LAB, OGN, GWEI) sit at exactly `maxApy = 365.00`. Bitget appears to use 365% as a boilerplate APR tier for a subset of new-listing Savings pools. **This is itself a testable observation**: the 365%-tier pool is a specific product SKU, and its pump-and-dump signal (if any) should be evaluated as a cohort separately from lower-APR pools.

Full ≥ 50% APR observation from probe scrape:

| Coin | APR | Status | Start |
|---|---|---|---|
| OGN | 365% | active (2) | 2026-06-16 |
| LAB | 365% | sold out (6) | 2026-05-12 |
| GWEI | 365% | active (2) | 2026-06-22 |
| TLM | 328.96% | active (2) | 2026-06-17 |
| DATA | 191% | active (2) | 2026-06-15 |
| ICNT | 177% | active (2) | 2026-06-24 |
| JST | 168.93% | active (2) | 2026-07-07 |
| RE | 142.67% | active (2) | 2026-06-19 |
| BREV | 126.53% | active (2) | 2026-07-01 |
| LA | 119.73% | active (2) | 2026-05-08 |
| HMSTR | 104.14% | active (2) | 2026-06-09 |
| BARD | 100% | active (2) | 2026-05-08 |
| PAXG | 99.99% | paused (4) | 2025-11-06 |
| GENIUS | 65.05% | active (2) | 2026-06-15 |
| YB | 63.24% | active (2) | 2026-06-09 |
| SLX | 55.85% | active (2) | 2026-07-01 |
| SKYAI | 52% | sold out (6) | 2026-05-26 |
| SXT | 51.72% | sold out (6) | 2026-05-08 |

18 pools at ≥ 50% APR. 3 already sold out. 15 in-flight. This is a real universe, not a synthetic one.

## 7. Missing fields on the list-view endpoint

The following fields from `docs/DATA_MODEL.md` are NOT present on the list-view SSR blob and must be handled differently:

- `pool_size_underlying` / `pool_size_usdt_at_open`: absent. `apyList[i].maxStepValue` is the **per-user cap** (1000 LAB for LAB), not the total pool size. Total pool size may require the product detail page (unknown source yet).
- `sold_out_ts`: absent. Derived from first-scrape-where-status-changed-to-6.
- `first_distribution_ts` / `last_distribution_ts`: absent for Savings (rolling reward accrual, no distribution event). Only structured products have `interestTime`.
- `close_ts` / `term_days`: for Savings with `lockModel: false` there is no close. Fixed-term products with `lockModel: true` may expose `period` and `periodType`.

**Impact on the hypothesis:** the "distribution unlock cliff" sub-hypothesis (H2) is NOT applicable to `Savings` products because Savings is rolling / flexible. H1 (soaking / high APR + sold out predicting dump) IS still applicable. H3 (announcement window) is applicable and easy: measure price behavior between `startTime` and `startTime + N days`, and between `startTime` and `sold_out_ts` (once we start tracking transitions).

## 8. Recommended scraper design (updated for reality)

1. **Endpoint**: `GET https://www.bitget.com/asia/earning` with a browser User-Agent.
2. **Parser**: extract `__NEXT_DATA__` script tag, parse JSON, iterate `listData[*].bizLineProductList[*].productList[*]` and `structuralList[*].bizLineProductGroup[*]`.
3. **Cadence for Phase 1**: 15 minutes. Bitget serves this as a normal web page; 4 req/hour will not trigger rate limits.
4. **Transitions to detect**: `status` change (2 → 6 = sold out), `startTime` first-seen, product first-appearance.
5. **What to store per product per scrape**: (event_id, first_seen_ts, last_seen_ts, current_status, apy, start_time, sold_out_first_seen_ts, ...) with SHA256 of raw HTML page for provenance.

## 9. Open questions the probe did not answer

- **Total pool size**: needs a probe of the product detail page (`https://www.bitget.com/asia/earning/savings-details?id=<productId>`). Deferred to Phase 1 Task 4 (before scraper goes live).
- **PoolX / Launchpool**: separate page, client-rendered. Different scraper. Phase 2 or later.
- **API rate limits for web page scrape**: not documented. Conservative 15-min cadence should be safe; increase if needed.
- **Historical products**: Bitget does not show closed / expired Savings pools on this page. Confirmed: catalog is forward-only from t0.

## 10. Decision

**Use the SSR blob path.** No API auth. No DOM parsing (JSON is embedded in the HTML, `__NEXT_DATA__` script tag, one regex extraction). Robust to CSS changes; brittle only if Bitget migrates to client-side rendering. Fall-back plan (browser-based headless scrape via Playwright) documented in a future SCRAPER update if that migration happens.

Move to Task 2 (data model implementation).
