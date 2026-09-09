#!/usr/bin/env bash
# Install / update Hotel Bell Elite nightly WhatsApp sales report cron on Lightsail.
# Safe: only adds/replaces the belleliteaccounts WhatsApp sales line; leaves other cron jobs alone.
# Crontab is OUTSIDE the app git tree, so normal git pull / code deploys do not remove this job.
# Re-run this script after changing APP_ROOT or Python path; not required on every deploy.
set -euo pipefail

APP_ROOT="${APP_ROOT:-/home/ubuntu/belleliteaccounts}"
if [[ -x "$APP_ROOT/venv/bin/python" ]]; then
  PYTHON_BIN="$APP_ROOT/venv/bin/python"
elif [[ -x "$APP_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$APP_ROOT/.venv/bin/python"
else
  echo "ERROR: no venv python under $APP_ROOT" >&2
  exit 1
fi

RUNNER="$APP_ROOT/scripts/run_scheduled_whatsapp_sales_reports.py"
if [[ ! -f "$RUNNER" ]]; then
  echo "ERROR: missing $RUNNER — deploy app code first." >&2
  exit 1
fi

chmod +x "$RUNNER" || true
mkdir -p "$APP_ROOT/logs"
LOG="$APP_ROOT/logs/whatsapp_schedule.log"
touch "$LOG"

CRON_SCHEDULE="${CRON_SCHEDULE:-59 23 * * *}"
MARKER="belleliteaccounts-whatsapp-sales"
TMP_CRON="$(mktemp)"

{
  echo "SHELL=/bin/bash"
  echo "PATH=/usr/local/bin:/usr/bin:/bin"
  crontab -l 2>/dev/null \
    | grep -vE '^(SHELL|PATH)=' \
    | grep -vF "$MARKER" \
    | grep -vF "$APP_ROOT/scripts/run_scheduled_whatsapp_sales_reports.py" \
    || true
  echo "$CRON_SCHEDULE TZ=Asia/Kolkata cd \"$APP_ROOT\" && \"$PYTHON_BIN\" \"$RUNNER\" >> \"$LOG\" 2>&1  # $MARKER"
} > "$TMP_CRON"

crontab "$TMP_CRON"
rm -f "$TMP_CRON"

echo "Installed belleliteaccounts WhatsApp sales cron:"
echo "  $CRON_SCHEDULE TZ=Asia/Kolkata → $RUNNER"
echo "  python: $PYTHON_BIN"
echo "  log: $LOG"
echo "Note: crontab survives git pull. Re-run this installer only if APP_ROOT/python path changes."
