# deploy/

OCI VM deployment for the Phase 1 scraper. See `docs/PHASE_1_EXECUTION_PLAN.md` §B2 Option A for context.

## Files

- `oci_setup.sh` — one-shot installer. Paste into an SSH session on a fresh Ubuntu 24.04 ARM VM.
- `run_scrape.sh` — systemd `ExecStart` target. Sources `.env`, runs the scraper, tees the JSON summary to `data/health.json`.
- `defi-investor-scraper.service` — systemd oneshot unit.
- `defi-investor-scraper.timer` — 15-minute cadence timer (`OnUnitActiveSec=15min`, `Persistent=true` so missed runs on boot catch up).
- `logrotate.conf` — daily rotation, keeps 14 compressed days of `/var/log/defi-investor/*.log`.
- `rotate_raw_captures.sh` — daily cron, deletes raw HTML captures older than 30 days.

## Prerequisites on the VM

Three env vars must be set in the SSH session before running `oci_setup.sh`:

```
export GH_TOKEN=<farhungers PAT with repo scope>
export SUPABASE_URL=<from your local .env>
export SUPABASE_SERVICE_ROLE_KEY=<from your local .env>
```

Then:

```
curl -sSL https://raw.githubusercontent.com/farhungers/defi-investor/main/deploy/oci_setup.sh?token=${GH_TOKEN} | bash
```

(Or clone first, then run `bash deploy/oci_setup.sh`.)

## Post-install checks

```
sudo systemctl list-timers defi-investor-scraper.timer
journalctl -u defi-investor-scraper.service -n 50 --no-pager
cat /opt/defi-investor/data/health.json
```

Expected: timer active, journal shows one clean scrape, health.json has `events_seen: ~399` and `events_upserted_remote == events_seen`.

## Retention policy

30-day rolling (Phase 1 default per `PHASE_1_EXECUTION_PLAN.md` §A3). If you switch to Backblaze archival later, add the b2 sync step BEFORE the delete in `rotate_raw_captures.sh`.
