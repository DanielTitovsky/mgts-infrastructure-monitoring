#!/usr/bin/env bash
# Disposable, uniquely named databases in the isolated LOCAL preview only.
set -euo pipefail
cd "$(dirname "$0")/.."
compose=(docker compose -p mgts-preview -f compose.preview.yml)
suffix="$(date +%s)_$$"
fresh="mgts_fresh_$suffix"
legacy="mgts_legacy_$suffix"
for db in "$fresh" "$legacy"; do
  "${compose[@]}" exec -T db createdb -U preview "$db"
done
# Exact pre-cutover baseline; never run DROP statements, even in this fixture.
git show 05a644fbbdef1c2c19b9d8393c9aff88b5018b5c:migrations.sql |
  "${compose[@]}" exec -T db psql -U preview -d "$legacy" -v ON_ERROR_STOP=1
"${compose[@]}" exec -T db psql -U preview -d "$legacy" -v ON_ERROR_STOP=1 -c "INSERT INTO users(email,username) VALUES ('migration@example.invalid','preserve_me');"
for db in "$fresh" "$legacy"; do
  "${compose[@]}" run --rm --no-deps -e DB_NAME="$db" migrate
  "${compose[@]}" run --rm --no-deps -e DB_NAME="$db" migrate
  version=$("${compose[@]}" exec -T db psql -U preview -d "$db" -Atc 'SELECT version_num FROM alembic_version')
  [[ "$version" == 20261124_0001 ]]
  tables=$("${compose[@]}" exec -T db psql -U preview -d "$db" -Atc "SELECT count(*) FROM information_schema.tables WHERE table_schema='public' AND table_name IN ('users','statuses','infrastructure_objects','defects')")
  [[ "$tables" == 4 ]]
done
preserved=$("${compose[@]}" exec -T db psql -U preview -d "$legacy" -Atc "SELECT count(*) FROM users WHERE username='preserve_me'")
[[ "$preserved" == 1 ]]
printf 'PASS fresh + legacy adoption + repeat + preservation. Test databases retained: %s %s\n' "$fresh" "$legacy"
