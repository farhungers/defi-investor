#!/bin/bash
# Wrapper executed by systemd. One scrape, writes health.json.
set -euo pipefail

INSTALL_DIR="/opt/defi-investor"
cd "${INSTALL_DIR}"

# shellcheck disable=SC1091
source .venv/bin/activate

# Load .env into env
set -o allexport
# shellcheck disable=SC1091
source .env
set +o allexport

# Scraper prints its JSON summary to stdout on success.
# Tee that JSON to data/health.json so uptime checks can read the last-good result.
python -m defi_investor.scraper | tee "${INSTALL_DIR}/data/health.json"
