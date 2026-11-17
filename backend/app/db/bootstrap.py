"""Применение `sql/schema.sql` при старте приложения.

Файл идемпотентный: дополняет схему из корневого `migrations.sql` полями,
которые нужны API (пароль пользователя, координаты объекта, таблица дефектов).
"""

from __future__ import annotations

import logging
from pathlib import Path

from app.db.session import engine

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parents[2] / "sql" / "schema.sql"


def split_statements(sql: str) -> list[str]:
    """Разбивает SQL-файл на отдельные выражения.

    Комментарии вида `-- ...` отбрасываются, поэтому точку с запятой внутри
    строковых литералов можно не экранировать (в нашей схеме таких нет).
    """
    without_comments = "\n".join(
        line for line in sql.splitlines() if not line.strip().startswith("--")
    )
    return [statement.strip() for statement in without_comments.split(";") if statement.strip()]


async def bootstrap_schema() -> None:
    if not SCHEMA_PATH.exists():
        raise RuntimeError(f"Не найден файл схемы: {SCHEMA_PATH}")

    statements = split_statements(SCHEMA_PATH.read_text(encoding="utf-8"))
    if not statements:
        return

    logger.info("Применяю схему %s (%d выражений)", SCHEMA_PATH, len(statements))
    async with engine.begin() as connection:
        # API и воркер стартуют одновременно: без блокировки параллельные ALTER/CREATE
        # могут упасть друг на друге. Блокировка снимается по окончанию транзакции.
        await connection.exec_driver_sql("SELECT pg_advisory_xact_lock(727001)")
        for statement in statements:
            await connection.exec_driver_sql(statement)
