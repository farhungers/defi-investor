# Operations runbook

Fast-lookup reference for recurring ops incidents. Living document. Add to it when a new incident class is diagnosed and resolved.

## Table of contents

1. [Scraper workflow is red](#1-scraper-workflow-is-red)
2. [Supabase project unreachable](#2-supabase-project-unreachable)
3. [gh CLI on wrong account](#3-gh-cli-on-wrong-account)
4. [A2b backfill not producing new labels](#4-a2b-backfill-not-producing-new-labels)
5. [Health check quick commands](#5-health-check-quick-commands)

---

## 1. Scraper workflow is red

**Symptoms:** `scrape.yml` runs on `gh run list --workflow=scrape.yml` show `failure`.

**Diagnosis order:**
1. Look at the annotation: `gh run view <run-id>`. Two common failure classes:
   - **Billing block** (job never starts, run under 10s): `"account payments have failed or spending limit needs to be increased."` The repo is private and consuming Actions minutes. Fix: `github.com/settings/billing` OR make repo public (`gh repo edit farhungers/defi-investor --visibility public --accept-visibility-change-consequences`).
   - **Real error** (job runs then fails): pull the log with `gh run view <run-id> --log-failed`. Common causes below.
2. `httpx.ConnectError: Name or service not known` on Supabase URL → see section 2.
3. `HTTP 429` from Bitget → rate-limited; back off temporarily.
4. Parser regressions on new Bitget layout: see `docs/PHASE_3_SESSION_2_LOG.md` (BGBTC parser drift pattern).

## 2. Supabase project unreachable

**Symptoms:** DNS fails for `ewcalrgayfpwpcoielrl.supabase.co`, or HTTP 521 from Cloudflare on all queries.

**Cause:** Supabase free tier auto-pauses after 7 days of no activity. Once paused, the project subdomain stops resolving.

**Fix:** Log in to `supabase.com/dashboard`, find project `ewcalrgayfpwpcoielrl`, click "Restore project". Wait 1-3 minutes for Postgres to come up. Verify with:

```bash
curl -s -o /dev/null -w "%{http_code}\n" -H "apikey: $KEY" "https://ewcalrgayfpwpcoielrl.supabase.co/rest/v1/earn_events?select=coin_name&limit=1"
```

Expected: `200`. `521` = backend still booting. `401` = auth-layer up but Postgres not accepting queries yet.

**Prevention:** `.github/workflows/keepalive.yml` writes a heartbeat every 3 days to keep the project active. If it stops running, this incident recurs.

## 3. gh CLI on wrong account

**Symptoms:** `gh` commands 404 on repos, or push rejected. This machine has 3 `gh` accounts (`farhungers`, `arbabfar`, `farhadmaildari-lang`); active can drift when working across projects.

**Diagnosis:** `gh auth status | head -5`. Active line shows current default.

**Fix:**

```bash
gh auth switch -u farhungers && gh auth setup-git
```

Always run before first `gh` command in a session, especially before `git push`.

## 4. A2b backfill not producing new labels

**Symptoms:** `python scripts/backfill_labels_v030.py` completes with `labeled_events: 0` even though new sold-out events exist.

**Diagnosis checklist:**
1. **Are candidate events found?** The backfill filter is `sold_out_first_seen_at IS NOT NULL` (ever-sold-out, not currently sold-out). Query manually: `select count(*) from earn_events where sold_out_first_seen_at is not null;`
2. **Are they being skipped as stale_anchor?** Bitget events need a row in `earn_events_status_log` with `new_status=6`. Binance events need only `sold_out_first_seen_at` (parser is a diff-detector).
3. **Are they being silently dropped?** `label_event` returns `{}` only if `sold_out_first_seen_at` is null (post-2026-08-17 fix; before that it returned `{}` on `sold_out=False` too).
4. **Fetch problems?** `unlabelable_reason` reveals: `no_daily_candles` (coin not on Bitget), `no_walk_candles` (Bitget 1m retention exhausted), `anchor_before_first_walk_bar` (paging bug or retention).

Run with `--retry-unlabelable` to re-attempt events with existing unlabelable rows.

## 5. Health check quick commands

```bash
# GitHub workflows recent status
gh run list --workflow=scrape.yml --limit 5
gh run list --workflow=keepalive.yml --limit 3

# Supabase health
curl -s -o /dev/null -w "%{http_code}\n" -H "apikey: $KEY" "https://ewcalrgayfpwpcoielrl.supabase.co/rest/v1/earn_events?select=coin_name&limit=1"

# A2b current coverage
python scripts/coverage_forecast.py

# Test suite
python -m pytest tests/ -q

# git remotes + current SHA
git log -1 --oneline
git remote -v
```
