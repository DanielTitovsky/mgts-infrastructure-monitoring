#!/usr/bin/env bash
set -euo pipefail

MARIMO_PASSWORD_FILE="${MARIMO_PASSWORD_FILE:-/run/secrets/marimo_password}"
PORT="${MARIMO_PORT:-8790}"

if [[ ! -r "$MARIMO_PASSWORD_FILE" || ! -s "$MARIMO_PASSWORD_FILE" ]]; then
  printf 'required Marimo password secret file is missing or empty\n' >&2
  exit 1
fi
if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || (( PORT < 1 || PORT > 65535 )); then
  printf 'invalid MARIMO_PORT\n' >&2
  exit 2
fi

exec marimo run /app/notebooks/dataset_workbench.py \
  --host 0.0.0.0 --port "$PORT" --token-password-file "$MARIMO_PASSWORD_FILE" --headless \
  > >(sed --unbuffered --regexp-extended 's/(access_token=)[^&[:space:]]+/\1[REDACTED]/g') 2>&1
