#!/usr/bin/env bash
set -euo pipefail

MARIMO_PASSWORD_FILE="${MARIMO_PASSWORD_FILE:-/run/secrets/marimo_password}"
PORT="${MARIMO_PORT:-8790}"
NOTEBOOK_SOURCE="/app/notebooks/ml_research.py"
NOTEBOOK_PATH="/data/notebooks/ml_research.py"

if [[ ! -r "$MARIMO_PASSWORD_FILE" || ! -s "$MARIMO_PASSWORD_FILE" ]]; then
  printf 'required Marimo password secret file is missing or empty\n' >&2
  exit 1
fi
if [[ ! "$PORT" =~ ^[0-9]{1,5}$ ]] || (( PORT < 1 || PORT > 65535 )); then
  printf 'invalid MARIMO_PORT\n' >&2
  exit 2
fi

if [[ ! -r "$NOTEBOOK_SOURCE" || ! -s "$NOTEBOOK_SOURCE" ]]; then
  printf 'bundled Marimo notebook is missing or empty\n' >&2
  exit 1
fi

mkdir -p -- "$(dirname -- "$NOTEBOOK_PATH")"
if [[ ! -e "$NOTEBOOK_PATH" && ! -L "$NOTEBOOK_PATH" ]]; then
  cp --no-clobber -- "$NOTEBOOK_SOURCE" "$NOTEBOOK_PATH"
fi
if [[ ! -f "$NOTEBOOK_PATH" || ! -w "$NOTEBOOK_PATH" ]]; then
  printf 'persistent Marimo notebook is missing or not writable\n' >&2
  exit 1
fi

exec marimo edit "$NOTEBOOK_PATH" \
  --host 0.0.0.0 --port "$PORT" --token-password-file "$MARIMO_PASSWORD_FILE" --headless --trusted \
  > >(sed --unbuffered --regexp-extended 's/(access_token=)[^&[:space:]]+/\1[REDACTED]/g') 2>&1
