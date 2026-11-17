# mgts-infrastructure-monitoring

Система мониторинга городской инфраструктуры МГТС: Nuxt-фронтенд, FastAPI-бэкенд
и PostgreSQL. Всё поднимается одной командой через Docker Compose.

## Быстрый старт

```bash
# из корня проекта
bash start-db.sh
```

Скрипт соберёт и запустит `db`, `backend` и `frontend`, дождётся готовности,
применит схему и (для пустой базы) добавит демо-данные.

| Сервис | Адрес |
| --- | --- |
| Frontend | <http://localhost:3000> |
| Swagger | <http://localhost:8000/docs> |
| Healthcheck | <http://localhost:8000/health> |
| PostgreSQL | `localhost:5432` |

Демо-вход: `admin` / `admin123`.

### Реальные данные вместо моков

По умолчанию во фронтенде включены моки (`frontend/config.ts`, `useMocks: true`).
Чтобы таблицы читали API, поставьте `useMocks: false` и пересоберите фронтенд:

```bash
docker compose up -d --build frontend
```

Запросы `/api/*` проксируются Nuxt-сервером на `http://backend:8000/api`
(переменная `API_PROXY_TARGET` в `docker-compose.yml`).

### Полезные команды

```bash
bash start-db.sh --db-only     # только PostgreSQL
docker compose logs -f         # логи всех сервисов
docker compose down            # остановить
docker compose down -v         # остановить и удалить данные БД
```

Порты можно переопределить в `.env` (`BACKEND_PORT`, `FRONTEND_PORT`, `DB_PORT`).

> Перед запуском Docker закройте локальные dev-серверы на тех же портах,
> иначе контейнеры не смогут занять `3000`/`8000`.

## Локальный запуск без Docker

- Frontend: `cd frontend && npm install && npm run dev`
- Backend: `cd backend && pip install -r requirements.txt && uvicorn app.main:app --reload --port 3001`
- БД: `bash start-db.sh --db-only`

Подробности по API — в [backend/README.md](backend/README.md).
