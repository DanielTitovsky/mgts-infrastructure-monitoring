#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n scripts/preview.sh
if scripts/preview.sh invalid >/dev/null 2>&1; then exit 1; fi
docker compose -p mgts-preview -f compose.preview.yml config --format json | uv run python -c '
import json,sys
c=json.load(sys.stdin); s=c["services"]
assert set(s)=={"db","migrate","minio","backend","frontend"}
assert not s["db"].get("ports") and not s["minio"].get("ports")
assert s["frontend"]["ports"][0]["host_ip"]=="127.0.0.1"
assert s["backend"]["environment"]["S3_ENDPOINT"]=="http://minio:9000"
assert s["migrate"]["command"] == ["alembic", "upgrade", "head"]
assert s["backend"]["depends_on"]["migrate"]["condition"] == "service_completed_successfully"
assert all("container_name" not in v for v in s.values())
print("preview configuration: PASS")'
uv run python - <<'CHECK'
from pathlib import Path
assert not Path('scripts/preview-schema.sql').exists()
assert not Path('migrations.sql').exists()
assert not Path('backend/sql/schema.sql').exists()
assert Path('backend/alembic.ini').exists()
assert Path('backend/migrations/versions').is_dir()
print('backend schema ownership: PASS')
CHECK
