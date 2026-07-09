# PHASE_1_EXECUTION_PLAN — remaining Phase 1 work, sequenced

**Author:** Vault (2026-07-09, end of Session 1)
**Audience:** the user (for account setup) and the next Vault session (for the code)
**Status:** authoritative plan for finishing Phase 1. Follow top to bottom.

## What this document is

Session 1 shipped Tasks 1-4 (API probe, data model, parser, end-to-end file-only scraper). Everything to the right of that line is blocked on user account creations. This document lists every setup step the user does, every code step Vault does after that, and the exact order.

## What "Phase 1 complete" means

Per `docs/CHARTER.md` phase gates: **scraper writing clean, provenanced event rows to Supabase for 30 continuous days with < 5% missing events.** Then the phase log is written, Phase 2 (labeling) opens.

---

## SECTION A — USER SETUP (do these before the next Vault session)

### A1. Create a Supabase project

**Why:** the event catalog needs persistent, queryable storage that survives ephemeral runners. JSONL on disk is fine for pilot; Supabase is the corpus of record.

**Steps:**
1. Go to `https://supabase.com/dashboard`.
2. Sign in with your normal account, OR create a fresh account if you want defi-investor isolated from mm-radar's Supabase project. **Recommended: fresh project** to keep schemas and quotas separate from mm-radar. Free tier is enough for 30 days of pilot data.
3. Click "New project".
   - **Name:** `defi-investor`
   - **Region:** same as mm-radar (probably `us-east-1` or wherever your mm-radar project is). If you don't remember, pick the region closest to where the scraper will run (see A2 for scraper location).
   - **Database password:** long random string. Store in your password manager. Vault will NOT need it (uses the API keys instead).
4. Wait for project to spin up (~2 minutes).
5. From the project dashboard, go to **Project Settings → API**. Copy two things:
   - **Project URL**: looks like `https://xyz.supabase.co`
   - **`service_role` key** (secret, has full DB write access): looks like `eyJhbGci...`
6. Paste both into your notes and hand to Vault when the next session starts. Vault will put them in the scraper's `.env` file.

**Also save (for your own records):**
- The `anon` public key (not needed by Vault, but useful if you build a dashboard later)

**Do not:**
- Do not enable RLS on the `earn_events` table yet. Phase 1 does not need row-level security. Phase 4 will.
- Do not create tables manually. Vault applies `db/schema.sql` in Task 5.

---

### A2. Pick a scheduler (three options, pick one)

**Recommendation: Option A (OCI VM).** You already have the `maildari` tenancy in Paris. Free tier ARM VM is ideal for a persistent 24/7 scraper. Persistent disk means raw HTML captures don't bloat a git repo.

If you don't want to touch OCI right now, Option B (GH Actions) is fine for the 30-day pilot with the caveat that raw captures pile up in the repo.

Option C (Supabase Edge Fn) works but has runtime limits; use only if you don't want to manage a VM at all.

#### Option A — Oracle Cloud VM (recommended)

**Steps:**
1. Sign in to `cloud.oracle.com`. Cloud Account Name: `maildari`. Region: Paris (or wherever you already have compute).
2. Menu → Compute → Instances → Create instance.
   - **Name:** `defi-investor-scraper`
   - **Image:** Canonical Ubuntu 24.04 LTS (or the current LTS)
   - **Shape:** `VM.Standard.A1.Flex` (ARM, free tier). 1 OCPU, 6 GB RAM is plenty.
   - **Networking:** create a new VCN or reuse existing. Public IPv4 address = Yes (needed for SSH from you; scraper doesn't need inbound).
   - **SSH keys:** upload your existing public key or let OCI generate one and download the private key.
3. Wait ~5 minutes for provisioning.
4. Confirm you can SSH in: `ssh ubuntu@<public_ip>` from your dev machine.
5. Basic hygiene once inside:
   - `sudo apt update && sudo apt upgrade -y`
   - `sudo apt install -y python3.12 python3.12-venv python3-pip git`
   - Create a non-root user for the scraper if you want (optional; `ubuntu` is fine).
6. Hand Vault: the public IP, SSH username, and your comfort level with letting Vault write install scripts. Vault will not SSH in on your behalf — Vault produces the setup script, you paste it.

**Optional:** create a Backblaze B2 bucket for cheap raw-capture archival if you want to preserve HTML older than 30 days. Not required for Phase 1.

#### Option B — GitHub Actions cron

**Steps:**
1. Create a new GitHub repo under `farhungers` named `defi-investor` (or similar). Private.
2. Vault will push the codebase from `C:\defi investor` after you greenlight.
3. In the repo → Settings → Secrets and variables → Actions → New repository secret:
   - `SUPABASE_URL` = value from A1 step 5
   - `SUPABASE_SERVICE_ROLE_KEY` = value from A1 step 5
4. Confirm to Vault: repo name, whether to force-push or start clean, whether raw HTML captures go in the repo or Backblaze.

**Warning:** raw HTML captures at 4/hour * 24 * 30 = 2880 files per month, ~1 MB each = ~2.9 GB in the repo per month. GitHub free tier soft-caps at 5 GB per repo. Fine for one month; problematic beyond that. Rotation policy: keep raw captures for 30 days, then move to Backblaze or delete. Decide now.

#### Option C — Supabase Edge Function

**Steps:**
1. In Supabase dashboard → Edge Functions → New function.
2. Vault writes the scraper as a Deno/TypeScript port of the Python scraper. This is extra work (Python code needs to be rewritten). Only pick if you strongly prefer to have zero VMs.
3. Set schedule via Supabase → Database → Cron → New cron job.

**Trade-off:** rewriting the scraper for Deno adds ~1 session. Runtime limit (2 min per invocation) is fine for the 15-min baseline scrape. Not viable if you ever want < 1-min cadence.

---

### A3. Decide the raw-capture retention policy

Answer one question: **how long do we keep the raw HTML files?**

- **30 days rolling** (recommended for pilot): scraper deletes raw captures older than 30 days. Enough for provenance during Phase 1 and for reparsing if a bug is found.
- **Forever, offloaded to Backblaze** (recommended for Phase 2+): scripts to nightly-sync raw captures to a B2 bucket, then delete locally. Backblaze B2 pricing: ~$6/TB/month. For 3 GB/month accumulation, that's < $0.10/month. Worth it long term.
- **Local only** (fine for a solo pilot): no archival, disk fills up over time. Only pick if you plan to keep the VM/repo forever and are OK with the disk growth.

Tell Vault which one. Vault wires the rotation script accordingly.

---

### A4. Decide the repo home

Two options:
1. **Public repo** under `farhungers/defi-investor`. Fine for the code; raw captures excluded via `.gitignore` already. Same GitHub-safety rule as mm-radar (no binaries, no secrets).
2. **Private repo** under `farhungers/defi-investor`. Recommended for now until you decide if the research is publishable.
3. **Don't push to GitHub yet.** Keep local at `C:\defi investor\` until Phase 1 concludes. Also fine.

Tell Vault which one. If pushing: give the exact repo URL after you create it.

---

## SECTION B — VAULT BUILD TASKS (do these after user provides A1 credentials + A2 choice)

### B1. Task 5: Supabase integration

**Blocked on:** A1 complete.

**Steps Vault will take:**
1. Vault creates `.env.example` documenting `SUPABASE_URL` and `SUPABASE_SERVICE_ROLE_KEY`. User pastes real values into `.env` (gitignored).
2. Vault applies `db/schema.sql` to Supabase via the SQL editor. User runs it (copy-paste), Vault confirms row types.
3. Vault adds `supabase-py` to dependencies (`pyproject.toml`).
4. Vault adds `src/defi_investor/db.py` with `SupabaseWriter` that batches upserts on `earn_events` and appends to `earn_events_status_log`.
5. Vault modifies `scraper.py` to call `SupabaseWriter.upsert(...)` after the JSONL write. File writes remain — Supabase is a mirror, not a replacement.
6. Vault adds unit tests for the batching and a smoke test that hits Supabase with a fake event (uses a `--dry-run` flag on the smoke test so it doesn't pollute prod data).
7. Vault runs the smoke test end-to-end. Verifies rows appear in Supabase.

**Success criteria:** 399 rows in `earn_events` on Supabase after one live scrape, all provenance fields populated, one row for LAB with correct fields.

**Kill:** if Supabase rejects the schema, halt and share the error verbatim with user. Do not silently adjust the schema.

---

### B2. Task 6: Scheduler wiring

**Blocked on:** A2 choice + (if OCI) A2 step 6 handoff / (if GH) A4 repo push.

**Option A wiring (OCI VM):**
1. Vault writes `deploy/oci_setup.sh` — the bash script the user pastes into their SSH session to install Python, clone the repo (or upload the tarball), install dependencies, set up systemd unit + timer.
2. Vault writes `deploy/defi-investor-scraper.service` — systemd unit that runs the scraper.
3. Vault writes `deploy/defi-investor-scraper.timer` — systemd timer for 15-minute cadence.
4. Vault writes `deploy/logrotate.conf` — rotate `/var/log/defi-investor/*.log`.
5. Vault writes `deploy/rotate_raw_captures.sh` — daily raw HTML rotation per A3 policy.
6. Vault writes the healthcheck: a script that reads `data/events/current.jsonl` and emits `{"last_scrape_ts": "...", "n_events": ...}` to `data/health.json`. Cron writes this every scrape.
7. User pastes the setup script into SSH. Confirms `sudo systemctl status defi-investor-scraper.timer` shows active.

**Option B wiring (GH Actions):**
1. Vault writes `.github/workflows/scrape.yml` — 15-min cron.
2. Vault writes the workflow to commit raw captures back to a `data-raw` branch (not main) so main stays clean. Retention handled by a nightly workflow that prunes old raw captures.
3. User creates the two secrets per A2 Option B step 3.
4. First run happens on the next cron tick.

**Option C wiring (Supabase Edge Fn):**
1. Vault writes a Deno port of the scraper.
2. Vault writes the Edge Function.
3. User deploys it via `supabase functions deploy` (Vault provides the CLI commands).
4. User sets the cron via Supabase dashboard.

**Success criteria:** three consecutive scheduled runs produce three raw captures and three catalog updates without human intervention.

**Kill:** if the schedule silently fails (no runs, no logs), halt and diagnose. Do not "just retry" without understanding.

---

### B3. Task 7: Monitoring and alerting

**Blocked on:** B2 complete and running for at least 48 hours.

**Steps:**
1. Vault adds `scripts/uptime_check.py` that reads the last N health.json entries or the last N Supabase rows by `last_seen_at` and reports:
   - Cadence health: gaps between consecutive scrapes > 30 min → alert.
   - Parser health: any row with `data_quality != 'complete'` → alert.
   - Status-transition alerts: any 2 → 6 transition (a pool sold out) → alert.
   - Coverage: n_events per scrape stable within ±10%.
2. Alerting channel: reuse the mm-radar Telegram bot with a new topic thread, OR create a new bot. **Ask user which.** If new: Vault provides BotFather instructions in the reply.
3. Alerts fire once per condition per hour to avoid spam.
4. Vault writes the uptime check as a nightly cron on the same VM (or a separate GH Actions job).

**Success criteria:** during any 7-day window, uptime alert fires only on real issues, not on healthy runs.

---

### B4. Task 8: PosStaking parser + product-detail probe

**Blocked on:** B2 complete (scheduler stable).

**Steps:**
1. Vault probes `https://www.bitget.com/asia/earning/savings-details?id=<productId>` (or the equivalent product detail URL). Log to `docs/PHASE_1_PROBE_LOG_v2.md`. Goal: extract total pool size and per-tier APR breakdowns not on the list page.
2. If the detail page has an SSR blob, Vault extends the scraper to fetch it per unique product_id once at first-seen, cache the detail forever (details rarely change), and enrich the event row with total pool size.
3. Vault confirms PosStaking rows are being captured correctly (they should already be, but validate).
4. Add `test_parser_posstaking.py` fixture-based tests.

**Success criteria:** every event row has either a populated `total_pool_size_underlying` or a `data_quality = 'incomplete'` tag naming the missing field.

**Kill:** if Bitget rate-limits or blocks the detail-page fetches, back off to list-page-only. Not fatal for H3 hypothesis.

---

### B5. Task 9: Phase 1 completion report

**Blocked on:** 30 consecutive days of B2 + B3 uptime.

**Steps:**
1. Vault writes `docs/PHASE_1_COMPLETION.md` covering:
   - Event count by product family
   - Distinct coins captured
   - Number of sold-out transitions observed
   - Uptime percentage over the 30 days
   - Any parser errors, schema drifts, or bug fixes during the window
   - What the Phase 2 AI needs to know to start labeling
2. User reads and approves.
3. Vault opens Phase 2 in a new file (`docs/PHASE_2_PLAN.md`).

**Success criteria:** ≥ 30 distinct new pools with observable open + sold-out timestamps, or ≥ 30 completed events by any reasonable definition.

**Kill:** any CHARTER kill criterion tripped (scraper blocked, n < 30, confounds unresolvable, etc.). Report to user.

---

## SECTION C — Sequencing and dependencies

```
User: A1 (Supabase) ─┐
                     ├─> Vault: B1 (Task 5 Supabase integration) ─┐
User: A4 (repo home) ┘                                            │
                                                                  ├─> Vault: B2 (Task 6 scheduler)
User: A2 (scheduler) ─┐                                           │
User: A3 (retention)  ┴─────────────────────────────────────────> ┘
                                                                          │
                                                                          ├─> 48h burn-in
                                                                          │
                                                                          ├─> Vault: B3 (Task 7 monitoring)
                                                                          │
                                                                          ├─> Vault: B4 (Task 8 detail probe)
                                                                          │
                                                                          └─> 30-day continuous uptime
                                                                                       │
                                                                                       └─> Vault: B5 (Task 9 completion)
                                                                                                     │
                                                                                                     └─> Phase 2 opens
```

**Blocking chain in plain English:** Supabase + scheduler + retention + repo home decisions all need to be done before Vault can do anything on Task 5. After that Vault can go on autopilot through B2, B3, B4 with brief user check-ins.

## SECTION D — Handoff to the user

When you have the credentials + choices, hand to the next Vault session with:

```
Phase 1 setup done:
- Supabase URL: <paste>
- Supabase service_role key: <paste>
- Scheduler choice: [OCI / GH Actions / Edge Fn]
- If OCI: VM public IP <paste>, SSH user <paste>
- If GH: repo URL <paste>
- Retention policy: [30-day rolling / Backblaze / local forever]
- Repo home: [private GH / public GH / stay local]
- Telegram: [reuse mm-radar bot / new bot / no alerts for pilot]

Please continue with B1 (Task 5).
```

Paste that into the next Vault session and Vault runs from there.

## SECTION E — Kill switches during Phase 1

Any of these tripped, Vault halts and reports:

1. Bitget rate-limits or blocks the scrape (HTTP 403, 429, or captcha detected in HTML).
2. Bitget schema changes (parser starts flagging `schema_drift` on > 5% of rows).
3. Supabase quota exceeded or auth broken.
4. Scheduler misses > 20% of runs in a 24h window.
5. User pulls the plug.

Halt, report, wait for user decision. Do not attempt workarounds without explicit approval.

## SECTION F — What Vault WILL NOT do without explicit user approval

- Push code to any git remote
- Create any account
- Modify DNS, buy domains, or set up hosting outside the three approved options
- Take live positions or emit trading signals (Phase 1 is data-only)
- Touch mm-radar, FAR, or WriterProject files
- Skip a kill criterion

## SECTION G — Estimated user time for setup

| Task | Time |
|---|---|
| A1 Supabase project | 10 minutes |
| A2 Option A OCI VM | 20 minutes |
| A2 Option B GH Actions | 5 minutes |
| A2 Option C Edge Fn | 5 minutes (Vault does the port work later, ~1 session) |
| A3 retention decision | 30 seconds |
| A4 repo home decision | 30 seconds |
| Handoff paste | 1 minute |

**Total: ~15 to 40 minutes** depending on scheduler choice.

## SECTION H — What Phase 2 will look like (preview, not commitment)

Once Phase 1 completes:
- Build the labeler consuming events + Bitget perp candles
- Port `PurgedKFold` and `PSR` from mm-radar
- Compute triple-barrier labels per event
- Compute confound tags
- Halt at n = 30 and report

Read `docs/METHOD.md` if you want the full plan now.

— Vault, 2026-07-09
