#!/bin/bash
# defi-investor — one-shot OCI Ubuntu 24.04 ARM setup.
#
# Paste this whole script into an SSH session on the VM as user `ubuntu`.
# It will:
#   1. Install python + git.
#   2. Clone farhungers/defi-investor to /opt/defi-investor.
#   3. Create venv, pip install -e .
#   4. Ask you to fill /opt/defi-investor/.env (Supabase creds).
#   5. Install systemd unit + timer + logrotate + raw-capture rotation.
#   6. Start the timer (15-min cadence).
#
# Required env before running:
#   export GH_TOKEN=<farhungers PAT with repo scope>
#   export SUPABASE_URL=<from .env locally>
#   export SUPABASE_SERVICE_ROLE_KEY=<from .env locally>
#
# All three must be set. Script aborts otherwise.

set -euo pipefail

: "${GH_TOKEN:?export GH_TOKEN before running}"
: "${SUPABASE_URL:?export SUPABASE_URL before running}"
: "${SUPABASE_SERVICE_ROLE_KEY:?export SUPABASE_SERVICE_ROLE_KEY before running}"

REPO_URL="https://x-access-token:${GH_TOKEN}@github.com/farhungers/defi-investor.git"
INSTALL_DIR="/opt/defi-investor"
LOG_DIR="/var/log/defi-investor"
SVC_USER="ubuntu"

echo "==> 1/6: apt update + install python + git"
sudo DEBIAN_FRONTEND=noninteractive apt-get update -y
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y \
    python3.12 python3.12-venv python3-pip git ca-certificates

echo "==> 2/6: clone repo to ${INSTALL_DIR}"
sudo mkdir -p "${INSTALL_DIR}"
sudo chown "${SVC_USER}:${SVC_USER}" "${INSTALL_DIR}"
if [ -d "${INSTALL_DIR}/.git" ]; then
    (cd "${INSTALL_DIR}" && git pull)
else
    git clone "${REPO_URL}" "${INSTALL_DIR}"
fi

echo "==> 3/6: venv + pip install"
cd "${INSTALL_DIR}"
python3.12 -m venv .venv
# shellcheck disable=SC1091
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e .
deactivate

echo "==> 4/6: write .env (mode 600)"
umask 077
cat > "${INSTALL_DIR}/.env" <<EOF
SUPABASE_URL=${SUPABASE_URL}
SUPABASE_SERVICE_ROLE_KEY=${SUPABASE_SERVICE_ROLE_KEY}
EOF
umask 022
chmod 600 "${INSTALL_DIR}/.env"

echo "==> 5/6: log dir + logrotate + raw-capture rotation cron"
sudo mkdir -p "${LOG_DIR}"
sudo chown "${SVC_USER}:${SVC_USER}" "${LOG_DIR}"
sudo cp "${INSTALL_DIR}/deploy/logrotate.conf" /etc/logrotate.d/defi-investor
sudo chmod 644 /etc/logrotate.d/defi-investor
# Daily raw-capture rotation via cron (30-day retention)
CRON_LINE="15 3 * * * ${INSTALL_DIR}/deploy/rotate_raw_captures.sh >> ${LOG_DIR}/rotate.log 2>&1"
( sudo crontab -u "${SVC_USER}" -l 2>/dev/null | grep -v rotate_raw_captures.sh ; echo "${CRON_LINE}" ) \
    | sudo crontab -u "${SVC_USER}" -

echo "==> 6/6: install systemd unit + timer, enable + start"
sudo cp "${INSTALL_DIR}/deploy/defi-investor-scraper.service" /etc/systemd/system/
sudo cp "${INSTALL_DIR}/deploy/defi-investor-scraper.timer" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now defi-investor-scraper.timer

echo "==> smoke test: one manual scrape"
sudo systemctl start defi-investor-scraper.service
sleep 3
sudo systemctl status --no-pager defi-investor-scraper.service | head -20 || true

echo
echo "==> DONE"
echo "Timer status:  sudo systemctl list-timers defi-investor-scraper.timer"
echo "Last run log:  journalctl -u defi-investor-scraper.service -n 50"
echo "Health JSON:   cat ${INSTALL_DIR}/data/health.json"
