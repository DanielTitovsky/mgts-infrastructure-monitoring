#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
bash -n scripts/preview.sh
if scripts/preview.sh invalid >/dev/null 2>&1; then exit 1; fi
docker compose -p mgts-preview -f compose.preview.yml config --format json | uv run python -c '
import json,sys
c=json.load(sys.stdin); s=c["services"]
assert set(s)=={"db","db-init","minio","backend","frontend"}
assert not s["db"].get("ports") and not s["minio"].get("ports")
assert s["frontend"]["ports"][0]["host_ip"]=="127.0.0.1"
assert s["backend"]["environment"]["S3_ENDPOINT"]=="http://minio:9000"
assert all("container_name" not in v for v in s.values())
print("preview configuration: PASS")'
uv run python - <<'PY'
from pathlib import Path
assert not Path('scripts/preview-schema.sql').exists(), 'duplicate schema must be removed'
sql=Path('migrations.sql').read_text()
assert 'DROP TABLE' not in sql.upper(), 'startup must not delete existing tables'
assert sql.count('CREATE TABLE IF NOT EXISTS') == 3
assert './migrations.sql:/schema.sql:ro' in Path('compose.preview.yml').read_text()
print('canonical schema ownership: PASS')
PY
