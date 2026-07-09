# SCRAPER — data acquisition contract for Phase 1

## 1. First task before writing any scraper code

Check whether Bitget publishes an Earn events API. Candidate endpoints to probe:

```
GET https://api.bitget.com/api/v2/earn/savings/product
GET https://api.bitget.com/api/v2/earn/savings/subscribe-info
GET https://api.bitget.com/api/v2/earn/loan/public/coin-info
GET https://api.bitget.com/api/v2/earn/pool-x/product-list
```

Reference: `https://www.bitget.com/api-doc/` (Earn section).

**If any of these return usable Earn product listings with APR, pool size, and timestamps, use the API path. Do not DOM-scrape.**

If the API only exposes user-account endpoints (not public product listings), fall back to DOM scraping of `https://www.bitget.com/asia/earning`.

## 2. Scraper contract

### 2.1 Cadence

- **High-frequency window**: every 60 seconds during the announce → open transition window for known upcoming pools
- **Low-frequency baseline**: every 15 minutes for the full Earn product list, to catch new pools and status transitions

### 2.2 Rate limits

Bitget public API rate limit is 20 requests per second per IP for market data endpoints. Earn-specific limits not documented. Assume 5 rps ceiling. Never exceed.

If DOM scraping: 1 request per 30 seconds. Use a browser user-agent identifying the traffic as research (`User-Agent: defi-investor-research/0.1 (contact: <user_email>)`). This is a courtesy, not required.

### 2.3 Output contract

Every scrape run produces:

1. **Raw capture** in `data/raw/YYYY-MM-DD/HH-MM-SS_<endpoint>.json` (or `.html` for DOM)
2. **SHA256** of raw capture computed and stored
3. **Parsed events** appended to `data/events/YYYY-MM.jsonl` (deduped by event_id)
4. **Supabase upsert** on `earn_events` keyed by event_id

If any step fails, no downstream side effects. Raw capture is atomic-write. Parser is idempotent.

### 2.4 Provenance requirement

Every field on every event row must be traceable to a byte range in a specific raw capture. This means:

- Parser records source endpoint + timestamp + SHA256 for each event it emits
- Do not enrich event rows from ambient state (e.g., "the price at the time we scraped"). If it is not in the raw capture, do not put it on the row. Enrichment happens in the labeler phase from separately-provenanced sources.

## 3. Endpoint probes to run first

Before writing any code, run these probes and record results in `docs/PHASE_1_PROBE_LOG.md`:

```bash
# Public Earn product listings
curl -s "https://api.bitget.com/api/v2/earn/savings/product?coin=USDT" | jq '.'
curl -s "https://api.bitget.com/api/v2/earn/pool-x/product-list" | jq '.'

# Confirm PoolX response shape
curl -s "https://api.bitget.com/api/v2/earn/pool-x/product-list?status=purchasable" | jq '.'

# Confirm perpetual candles endpoint for price sidecar
curl -s "https://api.bitget.com/api/v2/mix/market/candles?symbol=LABUSDT&productType=USDT-FUTURES&granularity=1H&limit=100" | jq '. | length'
```

Log:
- HTTP status
- Response schema (keys + types)
- Whether it lists the LAB pool at all
- Whether APR is expressed as decimal (0.365) or basis-point-adjacent (365)
- Whether timestamps are ms or seconds since epoch
- Whether the same endpoint returns closed pools (needed for historical catalog) or only active ones

If closed pools are not returned by any endpoint, the catalog is forward-only from t0. This is fine per the CHARTER, but note it in the log.

## 4. Parser design

### 4.1 One parser per product type

Do not write a "universal parser." PoolX response shape differs from Simple Earn Fixed shape. Ship five parsers, one per product family. Shared helpers only for timestamp coercion and SHA256.

### 4.2 Deterministic on version

Parser version goes into the event row (`scraper_version` field, e.g., `"0.1.0"`). If parser logic changes, bump the version. Re-run against archived raw captures to regenerate the catalog.

### 4.3 Timestamp handling

- All ts fields stored as ISO 8601 UTC with timezone suffix (`2026-07-01T08:00:00Z`).
- Never store epoch integers on the event row. Convert at parse time.
- Bitget API commonly returns milliseconds. Divide by 1000 before ISO conversion.

### 4.4 Missing fields policy

If the raw capture does not contain a required field (e.g., no `pool_size_usdt_at_open`), do NOT invent it. Store `null` and tag `data_quality: "incomplete"`. Incomplete rows are excluded from labeling but retained for provenance.

## 5. Scheduler

For Phase 1, run scraper as a cron job. Recommended:

**Option A: GitHub Actions cron** (like mm-radar). Free, ephemeral, but requires committing raw captures back to repo. Fine for low volume; problematic at scale. Repo size grows.

**Option B: Oracle Cloud Free Tier ARM VM.** User has an OCI tenancy (`maildari`, Paris region). Persistent disk, low ops. Recommended for this project since raw captures accumulate.

**Option C: Supabase Edge Function on schedule.** Simplest deploy. Limited runtime (2 min per invocation). Fine for the 15-minute low-frequency baseline; not viable for the 60-second high-frequency window.

Recommendation: **Option B (OCI VM)** with `cron` running a Python scraper writing to local disk + Supabase. Raw captures rotate daily, archived compressed after 30 days, backed up to Backblaze B2 (cheap object storage).

Do not decide this until user approves Phase 1. Recording the options here for the successor AI.

## 6. Supabase table creation (deferred)

Do not create `earn_events` in Supabase until Phase 1 is greenlit. Draft the migration SQL in `docs/DATA_MODEL.md` section 7. Apply when scraper is ready to write.

## 7. Secrets

Bitget public endpoints require no auth. Supabase writes require `service_role` key. Store in environment, never in repo. Add to `.gitignore`:

```
.env
.env.*
data/raw/*
!data/raw/.gitkeep
data/events/*.jsonl
!data/events/.gitkeep
```

Raw captures may contain incidental data Bitget considers proprietary. Do not commit them to a public repo. Keep the raw archive local or on Backblaze; commit only the schemas, parsers, and derived event catalog if the user chooses to share.

## 8. Failure modes to plan for

- **Bitget UI or API schema change.** Detected by parser failing to find required keys. Alert user; do not silently drop fields.
- **IP block.** Detected by 429 or 403. Back off exponentially; rotate to residential proxy only with user approval.
- **Timestamp drift.** Detected by same event_id appearing with different open_ts across scrapes. Log and reconcile to first-seen.
- **Race condition on sold_out_ts.** If pool opens and sells out within 60 seconds, high-frequency scraper may miss the exact moment. Record `sold_out_ts` as "first scrape where `sold_out = true`" and tag `sold_out_ts_precision: "coarse"`.

## 9. What Phase 1 delivers

- Scraper running on OCI VM (or GitHub Actions, if Option A chosen)
- `earn_events` table populated in Supabase
- `docs/PHASE_1_PROBE_LOG.md` with API probe results
- `docs/PHASE_1_LOG.md` written on phase completion, describing what was built and what surprised
- 30 days of uptime with < 5% missing events by event count

Do not proceed to Phase 2 (labeling) until this is stable.
