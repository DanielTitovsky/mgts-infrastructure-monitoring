from __future__ import annotations

import ast
import asyncio
import importlib.util
import io
import re
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path
from unittest.mock import AsyncMock, patch

from alembic.migration import MigrationContext
from alembic.operations import Operations


BACKEND = Path(__file__).resolve().parents[1]
REPOSITORY = BACKEND.parent
INITIAL_REVISION = BACKEND / "migrations" / "versions" / "20261124_0001_initial_schema.py"


def normalize_sql(sql: str) -> str:
    return " ".join(sql.split())


@dataclass(frozen=True)
class ColumnContract:
    sql_type: str
    nullable: bool = True
    default: str | None = None
    primary_key: bool = False
    unique: bool = False
    foreign_key: tuple[str, str, str] | None = None


def column(
    sql_type: str,
    *,
    nullable: bool = True,
    default: str | None = None,
    primary_key: bool = False,
    unique: bool = False,
    foreign_key: tuple[str, str, str] | None = None,
) -> ColumnContract:
    return ColumnContract(sql_type, nullable, default, primary_key, unique, foreign_key)


# Semantic contract for the original base schema and the API/worker additions.
# This is intentionally data, not a second copy of either legacy SQL script.
EXPECTED_SCHEMA = {
    "users": {
        "id": column("SERIAL", nullable=False, primary_key=True),
        "email": column("VARCHAR(255)", nullable=False, unique=True),
        "phone": column("VARCHAR(50)"),
        "username": column("VARCHAR(100)", nullable=False, unique=True),
        "role": column("VARCHAR(50)", nullable=False, default="'user'"),
        "update_at": column("TIMESTAMP", nullable=False, default="NOW()"),
        "created_at": column("TIMESTAMP", nullable=False, default="NOW()"),
        "password_hash": column("VARCHAR(255)"),
    },
    "statuses": {
        "id": column("SERIAL", nullable=False, primary_key=True),
        "type": column("VARCHAR(100)", nullable=False),
        "description": column("TEXT"),
    },
    "infrastructure_objects": {
        "id": column("SERIAL", nullable=False, primary_key=True),
        "imgUrl": column("TEXT"),
        "type": column("VARCHAR(100)"),
        "statusId": column(
            "INTEGER", foreign_key=("statuses", "id", "SET NULL")
        ),
        "place": column("TEXT"),
        "external_id": column("VARCHAR(100)"),
        "lat": column("DOUBLE PRECISION"),
        "lon": column("DOUBLE PRECISION"),
        "processing_status": column("VARCHAR(32)"),
        "processing_started_at": column("TIMESTAMP"),
        "processing_attempts": column("INTEGER", nullable=False, default="0"),
        "processing_error": column("TEXT"),
        "processed_at": column("TIMESTAMP"),
        "processed_img_url": column("TEXT"),
    },
    "defects": {
        "id": column("SERIAL", nullable=False, primary_key=True),
        "object_id": column(
            "INTEGER", foreign_key=("infrastructure_objects", "id", "SET NULL")
        ),
        "detection_id": column("INTEGER"),
        "defect_type": column("VARCHAR(100)", nullable=False),
        "defect_confidence": column("DOUBLE PRECISION"),
        "severity": column("VARCHAR(50)"),
        "recommended_action": column("VARCHAR(50)"),
        "created_at": column("TIMESTAMP", nullable=False, default="NOW()"),
        "updated_at": column("TIMESTAMP", nullable=False, default="NOW()"),
        "bbox": column("JSONB"),
        "source": column("VARCHAR(20)", nullable=False, default="'manual'"),
    },
}

EXPECTED_INDEXES = {
    "infrastructure_objects_processing_status_idx": (
        "infrastructure_objects",
        "processing_status",
    ),
    "defects_object_id_idx": ("defects", "object_id"),
    "infrastructure_objects_status_id_idx": ("infrastructure_objects", "statusId"),
}


def parse_column_contract(definition: str) -> tuple[str, ColumnContract]:
    match = re.match(r'\s*("[^"]+"|\w+)\s+(.+?)\s*$', definition, re.DOTALL)
    if match is None:
        raise AssertionError(f"Unrecognized column definition: {definition!r}")
    name = match.group(1).strip('"')
    clauses = match.group(2)
    type_match = re.match(
        r"(SERIAL|INTEGER|VARCHAR\(\d+\)|DOUBLE PRECISION|TIMESTAMP|TEXT|JSONB)(?=\s|$)",
        clauses,
        re.IGNORECASE,
    )
    if type_match is None:
        raise AssertionError(f"Unrecognized SQL type for {name}: {clauses!r}")
    sql_type = normalize_sql(type_match.group(1)).upper()
    default_match = re.search(
        r"\bDEFAULT\s+(.+?)(?=\s+PRIMARY KEY|\s+UNIQUE|\s+REFERENCES|$)",
        clauses,
        re.IGNORECASE,
    )
    reference_match = re.search(
        r"\bREFERENCES\s+(\w+)\(([^)]+)\)(?:\s+ON DELETE\s+((?:NO ACTION|SET NULL|SET DEFAULT|CASCADE|RESTRICT)))?",
        clauses,
        re.IGNORECASE,
    )
    primary_key = bool(re.search(r"\bPRIMARY KEY\b", clauses, re.IGNORECASE))
    contract = ColumnContract(
        sql_type=sql_type,
        nullable=not primary_key
        and not bool(re.search(r"\bNOT NULL\b", clauses, re.IGNORECASE)),
        default=(normalize_sql(default_match.group(1)) if default_match else None),
        primary_key=primary_key,
        unique=bool(re.search(r"\bUNIQUE\b", clauses, re.IGNORECASE)),
        foreign_key=(
            (
                reference_match.group(1),
                reference_match.group(2).strip('"'),
                (reference_match.group(3) or "").upper(),
            )
            if reference_match
            else None
        ),
    )
    return name, contract


def parse_migration_schema(
    ddl: str,
) -> tuple[dict[str, dict[str, ColumnContract]], dict[str, tuple[str, str]]]:
    schema: dict[str, dict[str, ColumnContract]] = {}
    for match in re.finditer(
        r"CREATE TABLE IF NOT EXISTS\s+(\w+)\s*\((.*?)\);",
        ddl,
        re.IGNORECASE | re.DOTALL,
    ):
        schema[match.group(1)] = dict(
            parse_column_contract(definition)
            for definition in match.group(2).split(",")
        )
    for match in re.finditer(
        r"ALTER TABLE\s+(\w+)\s+ADD COLUMN IF NOT EXISTS\s+([^;]+);",
        ddl,
        re.IGNORECASE,
    ):
        table = match.group(1)
        name, contract = parse_column_contract(match.group(2))
        schema.setdefault(table, {})[name] = contract

    indexes = {
        match.group(1): (match.group(2), match.group(3).strip('"'))
        for match in re.finditer(
            r'CREATE INDEX IF NOT EXISTS\s+(\w+)\s+ON\s+(\w+)\s*\(\s*("[^"]+"|\w+)\s*\)',
            ddl,
            re.IGNORECASE,
        )
    }
    return schema, indexes


def load_initial_revision():
    spec = importlib.util.spec_from_file_location("initial_schema", INITIAL_REVISION)
    if spec is None or spec.loader is None:
        raise AssertionError(f"Cannot load migration revision {INITIAL_REVISION}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MigrationOwnershipTests(unittest.TestCase):
    def test_api_worker_and_seed_do_not_mutate_schema(self) -> None:
        for relative_path in ("app/main.py", "worker.py", "seed.py"):
            with self.subTest(component=relative_path):
                tree = ast.parse((BACKEND / relative_path).read_text(encoding="utf-8"))
                names = {
                    node.id
                    for node in ast.walk(tree)
                    if isinstance(node, ast.Name)
                }
                self.assertNotIn("bootstrap_schema", names)
                self.assertNotIn("create_all", names)
                self.assertNotIn("stamp", names)

        config = (BACKEND / "app" / "core" / "config.py").read_text(encoding="utf-8")
        self.assertNotIn("db_bootstrap", config)
        self.assertFalse((BACKEND / "app" / "db" / "bootstrap.py").exists())

    def test_api_lifespan_does_not_bootstrap_schema(self) -> None:
        sys.path.insert(0, str(BACKEND))
        try:
            from app import main
        finally:
            sys.path.remove(str(BACKEND))

        async def run_lifespan() -> None:
            with (
                patch.object(main, "bootstrap_schema", new_callable=AsyncMock, create=True) as bootstrap,
                patch.object(main.storage, "ensure_bucket", new_callable=AsyncMock),
                patch.object(main, "dispose_engine", new_callable=AsyncMock),
            ):
                async with main.lifespan(main.app):
                    pass
                bootstrap.assert_not_awaited()

        asyncio.run(run_lifespan())

    def test_alembic_is_pinned_and_uses_the_async_database_configuration(self) -> None:
        requirements = (BACKEND / "requirements.txt").read_text(encoding="utf-8")
        self.assertRegex(requirements, r"(?m)^alembic==\d+\.\d+\.\d+$")
        self.assertTrue((BACKEND / "alembic.ini").is_file())
        env = (BACKEND / "migrations" / "env.py").read_text(encoding="utf-8")
        self.assertIn("settings.database_url", env)
        self.assertIn("create_async_engine", env)
        self.assertIn("run_sync", env)
        self.assertNotIn("command.stamp", env)

    def test_initial_revision_adopts_legacy_schemas_without_destructive_ddl(self) -> None:
        migration = load_initial_revision()
        output = io.StringIO()
        context = MigrationContext.configure(
            dialect_name="postgresql",
            opts={"as_sql": True, "output_buffer": output},
        )
        with Operations.context(context):
            migration.upgrade()
        ddl = output.getvalue()

        actual_schema, actual_indexes = parse_migration_schema(ddl)
        self.assertEqual(actual_schema, EXPECTED_SCHEMA)
        self.assertEqual(actual_indexes, EXPECTED_INDEXES)
        status_seed = re.search(
            r"INSERT INTO statuses\s*\(type, description\)\s*SELECT\s*'([^']+)',\s*'([^']+)'\s*"
            r"WHERE NOT EXISTS\s*\(SELECT 1 FROM statuses WHERE type = '([^']+)'\)",
            ddl,
            re.IGNORECASE,
        )
        self.assertIsNotNone(status_seed)
        self.assertEqual(status_seed.groups(), ("unrecognized", "Не распознано", "unrecognized"))
        self.assertNotIn("DROP ", ddl.upper())

    def test_initial_revision_refuses_unsupported_downgrade(self) -> None:
        migration = load_initial_revision()
        with self.assertRaisesRegex(RuntimeError, "cannot safely downgrade"):
            migration.downgrade()

    def test_legacy_schema_scripts_are_removed_after_parity_is_captured(self) -> None:
        self.assertFalse((REPOSITORY / "migrations.sql").exists())
        self.assertFalse((BACKEND / "sql" / "schema.sql").exists())


if __name__ == "__main__":
    unittest.main()
