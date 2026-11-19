# Backend — API мониторинга инфраструктуры МГТС

Базовый REST API на **FastAPI** с асинхронной работой с **PostgreSQL**
(SQLAlchemy 2 + asyncpg). Реализует контракт, который уже использует фронтенд:
пользователи, статусы, объекты инфраструктуры, дефекты и вход по JWT.

## Быстрый старт

### Через Docker (весь проект)

Из корня репозитория:

```bash
bash start-db.sh
```

Compose поднимет PostgreSQL, API и фронтенд. Swagger будет доступен на
<http://localhost:8000/docs>, API healthcheck — на <http://localhost:8000/health>.
Внутри docker-сети фронтенд обращается к API по адресу `http://backend:8000`
(передаётся через `API_PROXY_TARGET` в `docker-compose.yml`).

### Локально, без Docker

```bash
# 1. База данных (из корня проекта, один раз)
bash start-db.sh --db-only
#    либо: docker compose up -d db, затем применить migrations.sql

# 2. Зависимости бэкенда
cd backend
py -3 -m venv .venv
.venv\Scripts\activate            # Linux/macOS: source .venv/bin/activate
pip install -r requirements.txt

# 3. Демо-данные (необязательно, но удобно для проверки UI)
python seed.py

# 4. Запуск
uvicorn app.main:app --reload --port 3001
```

- Swagger: <http://127.0.0.1:3001/docs>
- Healthcheck: <http://127.0.0.1:3001/health>
- Порт `3001` совпадает с `devProxy` и `apiUrl` во фронтенде.

> Если фронтенд уже занял порт `3001`, освободите его или поменяйте
> `nitro.devProxy` в `frontend/nuxt.config.ts` и запустите API на другом порту.

## Подключение фронтенда

В `frontend/config.ts` выставить `useMocks: false`. Запросы пойдут на
`/api/...`, а Nuxt-прокси перенаправит их на `http://127.0.0.1:3001/api`.

Демо-пользователи после `python seed.py`:

| Логин | Пароль | Роль |
| --- | --- | --- |
| `admin` | `admin123` | admin |
| `operator` | `operator123` | operator |
| `engineer` | `engineer123` | engineer |

## Эндпоинты

| Метод | Путь | Описание |
| --- | --- | --- |
| `POST` | `/api/auth/login` | Вход по `username`/`password`, возвращает JWT и пользователя |
| `GET` | `/api/auth/me` | Текущий пользователь по `Authorization: Bearer <token>` |
| `GET`/`POST` | `/api/logout` | Заглушка: токен stateless, клиент удаляет его сам |
| `GET`/`POST` | `/api/users`, `/api/users/{id}` | Пользователи |
| `PUT`/`DELETE` | `/api/users/{id}` | Обновление и удаление |
| `GET`/`POST` | `/api/statuses`, `/api/statuses/{id}` | Статусы |
| `PUT`/`DELETE` | `/api/statuses/{id}` | Обновление и удаление |
| `GET`/`POST` | `/api/infrastructure-objects`, `/{id}` | Объекты инфраструктуры |
| `PUT`/`DELETE` | `/api/infrastructure-objects/{id}` | Обновление и удаление |
| `POST` | `/api/infrastructure-objects/{id}/photo` | Загрузка или замена фото (multipart-поле `file`) |
| `GET` | `/api/infrastructure-objects/{id}/photo` | Фото объекта из MinIO |
| `DELETE` | `/api/infrastructure-objects/{id}/photo` | Удаление фото |
| `GET`/`POST` | `/api/defects`, `/api/defects/{id}` | Дефекты |
| `PUT`/`DELETE` | `/api/defects/{id}` | Обновление и удаление |
| `GET` | `/health` | Состояние сервиса и БД |

## Формат ответов

Успех (`2xx`):

```json
{ "success": true, "data": { "...": "..." } }
```

Ошибка (`4xx`/`5xx`):

```json
{
  "success": false,
  "error": {
    "code": 404,
    "title": "Объект не найден",
    "description": "Объект с id=42 не существует.",
    "message": "Объект с id=42 не существует."
  }
}
```

Конверт совместим с `frontend/services/useRequest.ts`, поэтому карточки и таблицы
работают без изменений.

## Структура

```text
backend/
├── app/
│   ├── main.py                 # create_app, lifespan, CORS, обработчики ошибок
│   ├── core/
│   │   ├── config.py           # настройки, читает корневой .env
│   │   ├── security.py         # bcrypt + JWT
│   │   ├── errors.py           # AppError и единый формат ошибок
│   │   ├── storage.py          # MinIO/S3: загрузка и выдача фото
│   │   └── responses.py        # конверт успешного ответа
│   ├── db/
│   │   ├── base.py             # DeclarativeBase
│   │   ├── session.py          # async engine и get_session
│   │   └── bootstrap.py        # применение sql/schema.sql при старте
│   ├── models/                 # SQLAlchemy-модели таблиц
│   ├── schemas/                # Pydantic-схемы запросов/ответов
│   ├── services/               # бизнес-логика и запросы к БД
│   └── api/
│       ├── deps.py             # get_session, get_current_user, require_auth
│       ├── router.py           # сборка /api
│       └── routes/             # auth, users, statuses, objects, defects, health
├── sql/schema.sql              # идемпотентное дополнение схемы
├── seed.py                     # демо-данные
├── requirements.txt
└── main.py                     # запуск: uvicorn main:app
```

Слои повторяют подход из фронтенда и Go-проектов: транспорт (`api/routes`) →
сервисы (`services`) → модели (`models`), общие вещи — в `core`.
Зависимости передаются через `Depends`, ручной сборки графа нет.

## Схема БД

Базовая схема создаётся корневым `migrations.sql` (её применяет `start-db.sh`).
`backend/sql/schema.sql` при старте **дополняет** её:

- `users.password_hash` — для входа;
- `infrastructure_objects.external_id`, `lat`, `lon` — для карты и таблицы;
- таблица `defects` — результаты распознавания;
- индексы по `defects.object_id` и `infrastructure_objects."statusId"`.

Фото объектов хранятся в MinIO, а в `infrastructure_objects."imgUrl"` лежит
ключ файла вида `objects/{id}/{uuid}.jpg`. API отдаёт клиенту готовую ссылку
`/api/infrastructure-objects/{id}/photo`, поэтому менять схему БД не нужно.

Файл идемпотентный (`ADD COLUMN IF NOT EXISTS`, `CREATE TABLE IF NOT EXISTS`),
поэтому может применяться при каждом запуске. Отключается через `DB_BOOTSTRAP=false`.

## Переменные окружения

Обязательные берутся из `.env` в корне проекта: `DB_USER`, `DB_PASSWORD`,
`DB_NAME`, `DB_PORT`. Остальные — необязательные:

| Переменная | По умолчанию | Назначение |
| --- | --- | --- |
| `DB_HOST` | `localhost` | Хост PostgreSQL |
| `DB_ECHO` | `false` | Логировать SQL |
| `DB_BOOTSTRAP` | `true` | Применять `sql/schema.sql` при старте |
| `JWT_SECRET` | `dev-secret-change-me` | Секрет подписи токена (задать в проде) |
| `JWT_EXPIRES_MINUTES` | `720` | Время жизни токена |
| `AUTH_REQUIRED` | `false` | Требовать токен для CRUD-эндпоинтов |
| `S3_ENDPOINT` | `http://localhost:9000` | Адрес MinIO/S3 (в Docker — `http://minio:9000`) |
| `S3_ACCESS_KEY` | `minioadmin` | Логин MinIO |
| `S3_SECRET_KEY` | `minioadmin` | Пароль MinIO |
| `S3_BUCKET` | `mgts-objects` | Bucket для фото объектов |
| `S3_REGION` | `us-east-1` | Регион S3 |
| `MAX_PHOTO_SIZE_MB` | `5` | Максимальный размер фото |
| `CORS_ORIGINS` | localhost:3000/3001 | Список origin через запятую |

`AUTH_REQUIRED=false` оставлен специально: у фронтенда пока нет экрана входа,
поэтому таблицы должны открываться без токена. После добавления формы входа
достаточно поставить `AUTH_REQUIRED=true` — защита уже подключена ко всем
CRUD-роутерам.

## Дальше по плану

- `POST /api/upload` (multipart `pictures`) и очередь обработки для `worker.py`;
- `GET /frames/{id}/image` для просмотра кадров;
- фильтры и пагинация (`severity`, `action`, `limit`, `offset`);
- экспорт `GET /api/defects/export?format=csv`;
- загрузка `imgUrl` в файловое хранилище.
