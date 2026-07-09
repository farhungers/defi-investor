#!/bin/bash
# Daily job — delete raw HTML captures older than 30 days (rolling retention).
# Runs from cron via ubuntu user.
#
# Retention policy per PHASE_1_EXECUTION_PLAN.md §A3 default (30-day rolling).
# If we later add Backblaze archival, sync must happen BEFORE this deletes.
set -euo pipefail

RAW_DIR="/opt/defi-investor/data/raw"
RETENTION_DAYS=30

if [ ! -d "${RAW_DIR}" ]; then
    echo "no raw dir, nothing to rotate"
    exit 0
fi

# Delete .html files older than RETENTION_DAYS
BEFORE=$(find "${RAW_DIR}" -type f -name "*.html" -mtime "+${RETENTION_DAYS}" | wc -l)
find "${RAW_DIR}" -type f -name "*.html" -mtime "+${RETENTION_DAYS}" -delete
# Also prune empty date dirs
find "${RAW_DIR}" -mindepth 1 -type d -empty -delete

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) rotated: deleted ${BEFORE} html files older than ${RETENTION_DAYS}d"
