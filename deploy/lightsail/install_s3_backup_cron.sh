#!/usr/bin/env bash
# Install / update the every-6-hours belleliteaccounts S3 backup cron.
# Safe: only adds/replaces the belleliteaccounts backup line; leaves other cron jobs alone.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
RUNNER="$ROOT/run_s3_backup.sh"
CRON_SCHEDULE="${CRON_SCHEDULE:-0 */6 * * *}"
BACKUP_LOG="${BACKUP_LOG:-$HOME/.belleliteaccounts-backup/backup.log}"
MARKER="belleliteaccounts-s3-backup"
TMP_CRON="$(mktemp)"

chmod +x "$ROOT/run_s3_backup.sh" || true
mkdir -p "$(dirname "$BACKUP_LOG")"
touch "$BACKUP_LOG"

{
  echo "SHELL=/bin/bash"
  echo "PATH=/usr/local/bin:/usr/bin:/bin"
  crontab -l 2>/dev/null \
    | grep -vE '^(SHELL|PATH)=' \
    | grep -vF "$MARKER" \
    | grep -vF "$RUNNER" \
    || true
  echo "$CRON_SCHEDULE HOME=$HOME \"$RUNNER\" >> \"$BACKUP_LOG\" 2>&1  # $MARKER"
} > "$TMP_CRON"

crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed belleliteaccounts S3 backup cron:"
echo "  $CRON_SCHEDULE → $RUNNER"
echo "  log: $BACKUP_LOG"
