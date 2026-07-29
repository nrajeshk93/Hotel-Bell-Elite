#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENV_FILE="${BACKUP_ENV_FILE:-$HOME/.belleliteaccounts-backup/credentials.env}"
PYTHON_BIN="${PYTHON_BIN:-}"

if [[ -z "$PYTHON_BIN" ]]; then
  if [[ -x /home/ubuntu/belleliteaccounts/venv/bin/python ]]; then
    PYTHON_BIN=/home/ubuntu/belleliteaccounts/venv/bin/python
  else
    PYTHON_BIN="$(command -v python3)"
  fi
fi

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing credentials file: $ENV_FILE" >&2
  exit 1
fi

# Ensure boto3 exists in the chosen interpreter (install into user site if needed).
if ! "$PYTHON_BIN" -c "import boto3" >/dev/null 2>&1; then
  "$PYTHON_BIN" -m pip install --user -q boto3
fi

export BACKUP_ENV_FILE="$ENV_FILE"
exec "$PYTHON_BIN" "$ROOT/backup_sqlite_to_s3.py" "$@"
