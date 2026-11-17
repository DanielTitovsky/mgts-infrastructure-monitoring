#!/usr/bin/env bash
set -euo pipefail

# --- 0. Пауза в конце ---
pause_at_end() {
    local exit_code=$?
    if [ -t 0 ] && [ -t 1 ]; then
        echo ""
        if [ "$exit_code" -ne 0 ]; then
            echo "Скрипт завершился с ошибкой (код $exit_code)."
        fi
        read -r -p "Нажмите Enter, чтобы закрыть окно..." _
    fi
    exit "$exit_code"
}
trap pause_at_end EXIT

# --- 1. Переходим в папку проекта ---
ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$ROOT_DIR"

ENV_FILE=".env"
COMPOSE_FILE="docker-compose.yml"
MIGRATION_FILE="migrations.sql"
MODE="${1:-}"

case "$MODE" in
    ""|"--all"|"--db-only") ;;
    *)
        echo "Неизвестный аргумент: $MODE" >&2
        echo "Использование: bash start-db.sh [--all|--db-only]" >&2
        exit 1
        ;;
esac

# --- 2. .env ---
if [ ! -f "$ENV_FILE" ]; then
    echo "Файл $ENV_FILE не найден. Создаю со значениями по умолчанию..."
    cat > "$ENV_FILE" <<EOF
DB_USER=Osiris
DB_PASSWORD=admin
DB_NAME=mtgsHack
DB_PORT=5432
CONTAINER_NAME=mtgs_hack_db
EOF
else
    echo "Использую существующий $ENV_FILE"
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

: "${DB_USER:?DB_USER не задан в .env}"
: "${DB_PASSWORD:?DB_PASSWORD не задан в .env}"
: "${DB_NAME:?DB_NAME не задан в .env}"
: "${DB_PORT:?DB_PORT не задан в .env}"
: "${CONTAINER_NAME:?CONTAINER_NAME не задан в .env}"

BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

# --- 3. Проверки docker/compose ---
if ! command -v docker >/dev/null 2>&1; then
    echo "Ошибка: docker не установлен." >&2
    exit 1
fi

if docker compose version >/dev/null 2>&1; then
    COMPOSE_CMD="docker compose"
elif command -v docker-compose >/dev/null 2>&1; then
    COMPOSE_CMD="docker-compose"
else
    echo "Ошибка: не найден ни 'docker compose', ни 'docker-compose'." >&2
    exit 1
fi

if [ ! -f "$COMPOSE_FILE" ]; then
    echo "Ошибка: файл $COMPOSE_FILE не найден в $ROOT_DIR." >&2
    exit 1
fi

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "Ошибка: файл миграции $MIGRATION_FILE не найден в $ROOT_DIR." >&2
    exit 1
fi

# --- 4. Запуск ---
if [ "$MODE" = "--db-only" ]; then
    echo "Запускаю только PostgreSQL..."
    $COMPOSE_CMD up -d db
else
    echo "Собираю и запускаю проект: db + backend + frontend..."
    $COMPOSE_CMD up -d --build
fi

# --- 5. Ожидание PostgreSQL ---
echo -n "Ожидаю готовности PostgreSQL"
for i in $(seq 1 60); do
    if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        echo " — готово!"
        break
    fi
    echo -n "."
    sleep 1

    if [ "$i" -eq 60 ]; then
        echo ""
        echo "Ошибка: БД не поднялась за 60 секунд. Логи:" >&2
        $COMPOSE_CMD logs db
        exit 1
    fi
done

# --- 6. Страховка: схема из migrations.sql ---
# При новом томе файл применяется автоматически через docker-entrypoint-initdb.d.
# Здесь проверяем только случай, когда том уже был, но схема отсутствует.
HAS_USERS="$(docker exec -i "$CONTAINER_NAME" psql \
    -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT to_regclass('public.users') IS NOT NULL;" \
    | tr -d '[:space:]')"

if [ "$HAS_USERS" != "t" ]; then
    echo "Схема не найдена, применяю $MIGRATION_FILE..."
    docker exec -i "$CONTAINER_NAME" psql \
        -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 \
        < "$MIGRATION_FILE"
else
    echo "Схема уже создана, миграция пропущена (данные сохраняются)."
fi

# --- 7. Только БД? ---
if [ "$MODE" = "--db-only" ]; then
    echo ""
    echo "============================================"
    echo "PostgreSQL готов!"
    echo "  Host:     localhost"
    echo "  Port:     ${DB_PORT}"
    echo "  User:     ${DB_USER}"
    echo "  Password: ${DB_PASSWORD}"
    echo "  Database: ${DB_NAME}"
    echo "============================================"
    echo ""
    echo "Таблицы:"
    docker exec -i "$CONTAINER_NAME" psql -U "$DB_USER" -d "$DB_NAME" -c "\dt"
    echo ""
    echo "Остановка: $COMPOSE_CMD down"
    exit 0
fi

# --- 8. Ожидание backend и frontend ---
wait_healthy() {
    local service="$1"
    local attempts="$2"
    local container_id status

    for _ in $(seq 1 "$attempts"); do
        container_id="$($COMPOSE_CMD ps -q "$service" 2>/dev/null || true)"
        if [ -n "$container_id" ]; then
            status="$(docker inspect \
                -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}{{.State.Status}}{{end}}' \
                "$container_id" 2>/dev/null || echo unknown)"

            case "$status" in
                healthy) return 0 ;;
                unhealthy|exited|dead) return 1 ;;
            esac
        fi
        sleep 1
    done

    return 1
}

echo -n "Ожидаю готовности backend"
if wait_healthy backend 90; then
    echo " — готово!"
else
    echo ""
    echo "Ошибка: backend не поднялся. Логи:" >&2
    $COMPOSE_CMD logs backend
    exit 1
fi

echo -n "Ожидаю готовности frontend"
if wait_healthy frontend 120; then
    echo " — готово!"
else
    echo ""
    echo "Ошибка: frontend не поднялся. Логи:" >&2
    $COMPOSE_CMD logs frontend
    exit 1
fi

# --- 9. Демо-данные для пустой базы ---
USER_COUNT="$(docker exec -i "$CONTAINER_NAME" psql \
    -U "$DB_USER" -d "$DB_NAME" -tAc "SELECT count(*) FROM users;" \
    | tr -d '[:space:]')"

if [ "$USER_COUNT" = "0" ]; then
    echo "База пустая, добавляю демо-данные..."
    if ! $COMPOSE_CMD exec -T backend python seed.py; then
        echo "Предупреждение: не удалось добавить демо-данные." >&2
    fi
fi

# --- 10. Итог ---
echo ""
echo "============================================"
echo "Проект запущен!"
echo "  Frontend:    http://localhost:${FRONTEND_PORT}"
echo "  Swagger:     http://localhost:${BACKEND_PORT}/docs"
echo "  Healthcheck: http://localhost:${BACKEND_PORT}/health"
echo "  PostgreSQL:  localhost:${DB_PORT} (${DB_NAME}, ${DB_USER})"
echo ""
echo "  Демо-вход:   admin / admin123"
echo "  Реальные данные: useMocks: false в frontend/config.ts"
echo ""
echo "  Логи:        $COMPOSE_CMD logs -f"
echo "  Остановка:   $COMPOSE_CMD down"
echo "  Сброс БД:    $COMPOSE_CMD down -v"
echo "============================================"
echo ""
echo "Контейнеры:"
$COMPOSE_CMD ps
