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

# --- 1. .env ---
ENV_FILE=".env"

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

COMPOSE_FILE="docker-compose.yml"
MIGRATION_FILE="migrations.sql"   # <-- поправлено под ваш файл

# --- 2. Проверка docker/compose ---
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

if [ ! -f "$MIGRATION_FILE" ]; then
    echo "Ошибка: файл миграции $MIGRATION_FILE не найден в текущей папке." >&2
    exit 1
fi

# --- 3. Генерация docker-compose.yml ---
echo "Генерирую $COMPOSE_FILE на основе $ENV_FILE..."
cat > "$COMPOSE_FILE" <<EOF
version: '3.8'

services:
  db:
    image: postgres:15-alpine
    container_name: ${CONTAINER_NAME}
    restart: always
    env_file:
      - .env
    environment:
      POSTGRES_USER: \${DB_USER}
      POSTGRES_PASSWORD: \${DB_PASSWORD}
      POSTGRES_DB: \${DB_NAME}
    ports:
      - "\${DB_PORT}:5432"
    volumes:
      - postgres_data:/var/lib/postgresql/data

volumes:
  postgres_data:
EOF

# --- 4. Запуск ---
echo "Запускаю контейнер..."
$COMPOSE_CMD up -d

# --- 5. Ожидание ---
echo -n "Ожидаю готовности PostgreSQL"
for i in $(seq 1 30); do
    if docker exec "$CONTAINER_NAME" pg_isready -U "$DB_USER" -d "$DB_NAME" >/dev/null 2>&1; then
        echo " — готово!"
        break
    fi
    echo -n "."
    sleep 1

    if [ "$i" -eq 30 ]; then
        echo ""
        echo "Ошибка: БД не поднялась за 30 секунд. Логи:" >&2
        $COMPOSE_CMD logs db
        exit 1
    fi
done

# --- 6. Миграция через stdin (без путей!) ---
echo "Применяю миграцию $MIGRATION_FILE..."

# ВАЖНО: в Git Bash на Windows перед путём с '/' иногда нужно ставить MSYS_NO_PATHCONV=1,
# но здесь мы путь и не передаём — читаем локальный файл и отдаём в stdin.
docker exec -i "$CONTAINER_NAME" psql \
    -U "$DB_USER" \
    -d "$DB_NAME" \
    -v ON_ERROR_STOP=1 \
    < "$MIGRATION_FILE"

echo "Миграция успешно применена."

# --- 7. Итог ---
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
echo "Подключение:"
echo "  psql -h localhost -p ${DB_PORT} -U ${DB_USER} -d ${DB_NAME}"
echo ""
echo "Остановка: $COMPOSE_CMD down"