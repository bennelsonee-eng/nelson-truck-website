#!/usr/bin/env bash
# Install the nightly Typesense reindex systemd timer on titan-prod.
# Run ON the server:
#   bash /home/titan/titan-truck-website/app/scripts/deploy/install-reindex-timer.sh
#
# Idempotent: re-copies the unit files, reloads systemd, (re)enables the timer.
set -euo pipefail

SRC="/home/titan/titan-truck-website/app/scripts/deploy"
for unit in titan-reindex.service titan-reindex.timer; do
  sudo install -m 0644 "$SRC/$unit" "/etc/systemd/system/$unit"
  echo "installed /etc/systemd/system/$unit"
done

sudo systemctl daemon-reload
sudo systemctl enable --now titan-reindex.timer
echo "timer enabled + active. Next run:"
systemctl list-timers titan-reindex.timer --no-pager | grep titan-reindex || true
echo "Manual run anytime: sudo systemctl start titan-reindex.service  (log: /home/titan/reindex-typesense.log)"
