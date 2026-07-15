#!/usr/bin/env bash
# backup-titan.sh — Daily backup script for the Titan website.
#
# Drops a timestamped PostgreSQL dump + tar.gz of /static/brand_images
# into /home/titan/backups/, then prunes anything older than 14 days.
#
# Install (one-time):
#   sudo install -m 755 backup-titan.sh /usr/local/bin/backup-titan.sh
#   sudo install -m 644 backup-titan.service /etc/systemd/system/
#   sudo install -m 644 backup-titan.timer   /etc/systemd/system/
#   sudo systemctl daemon-reload
#   sudo systemctl enable --now backup-titan.timer
#
# Manual run:
#   /usr/local/bin/backup-titan.sh
set -euo pipefail

TS=$(date +%Y%m%d_%H%M%S)
BACKUP_DIR="/home/titan/backups"
STATIC_DIR="/home/titan/titan-truck-website/app/backend/static"
KEEP_DAYS=14

mkdir -p "$BACKUP_DIR"
cd "$BACKUP_DIR"

echo "[$(date -Iseconds)] backup-titan start (TS=${TS})"

# DB — custom-format pg_dump, compressed
docker exec titan_postgres pg_dump -U postgres --format=custom --compress=9 -d titan_web \
    > "titan_web_${TS}.dump"
echo "  wrote titan_web_${TS}.dump ($(du -h "titan_web_${TS}.dump" | cut -f1))"

# Static brand_images — tar gz (PDFs are already compressed; that's fine)
tar czf "brand_images_${TS}.tar.gz" -C "$STATIC_DIR" brand_images
echo "  wrote brand_images_${TS}.tar.gz ($(du -h "brand_images_${TS}.tar.gz" | cut -f1))"

# Retention — delete anything older than KEEP_DAYS days
find "$BACKUP_DIR" -maxdepth 1 -type f \
    \( -name 'titan_web_*.dump' -o -name 'brand_images_*.tar.gz' \) \
    -mtime "+${KEEP_DAYS}" -print -delete

echo "[$(date -Iseconds)] backup-titan done"
echo "  ${BACKUP_DIR} now contains:"
ls -lh "$BACKUP_DIR" | tail -n +2
