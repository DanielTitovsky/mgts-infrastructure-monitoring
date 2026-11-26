#!/usr/bin/env bash
set -euo pipefail

MARIMO_PASSWORD_FILE="${MARIMO_PASSWORD_FILE:-/run/secrets/marimo_password}"
PORT="${MARIMO_PORT:-8790}"
NOTEBOOK_SOURCE="/app/notebooks/cabinet_gallery.md"
NOTEBOOK_PATH="/data/notebooks/cabinet_gallery.md"

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

if [[ -n "${MGTS_DATASET_S3_ENDPOINT:-}" ]]; then
  if [[ -r /run/secrets/dataset_access_key && -r /run/secrets/dataset_secret_key ]]; then
    MGTS_DATASET_S3_ACCESS_KEY=$(</run/secrets/dataset_access_key)
    MGTS_DATASET_S3_SECRET_KEY=$(</run/secrets/dataset_secret_key)
    export MGTS_DATASET_S3_ACCESS_KEY MGTS_DATASET_S3_SECRET_KEY
  fi
  MGTS_FINAL_MANIFEST=$(python -m mgts_data_pipeline.minio_materials --verify-labels-and-models --print-path)
  export MGTS_FINAL_MANIFEST
  data_dir=$(dirname -- "$MGTS_FINAL_MANIFEST")
  export MGTS_CABINET_OOF="$data_dir/cabinet-oof-predictions-v1.json"
  export MGTS_REFERENCE_INDEX="$data_dir/cabinet-final-index-v1.json"
  export MGTS_BOX_REPORT="$data_dir/cabinet-boxes.json"
  export MGTS_MLP_HEAD="$data_dir/cabinet-mlp-head-v1.json"
  printf 'MinIO: verified organizer workbooks, dataset and model outputs\n'
fi
python -m mgts_data_pipeline.marimo_ai_config

exec marimo edit "$NOTEBOOK_PATH" \
  --host 0.0.0.0 --port "$PORT" --token-password-file "$MARIMO_PASSWORD_FILE" --headless --trusted \
  > >(sed --unbuffered --regexp-extended 's/(access_token=)[^&[:space:]]+/\1[REDACTED]/g') 2>&1
