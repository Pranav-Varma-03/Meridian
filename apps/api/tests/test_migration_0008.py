from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa


def _load_migration() -> ModuleType:
    path = (
        Path(__file__).parents[1] / "alembic/versions/0008_add_derived_chunk_context.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0008", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_derived_context_migration_is_additive_and_nullable(monkeypatch) -> None:
    migration = _load_migration()

    class FakeOperations:
        def __init__(self) -> None:
            self.columns: list[tuple[str, sa.Column]] = []

        def add_column(self, table_name: str, column: sa.Column) -> None:
            self.columns.append((table_name, column))

    fake_op = FakeOperations()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    assert [
        (table, column.name, column.nullable) for table, column in fake_op.columns
    ] == [
        ("document_chunks", "derived_context_text", True),
        ("document_chunks", "derived_context_version", True),
    ]


def test_derived_context_downgrade_removes_only_new_columns(monkeypatch) -> None:
    migration = _load_migration()

    class FakeOperations:
        def __init__(self) -> None:
            self.columns: list[str] = []

        def drop_column(self, _table_name: str, column_name: str) -> None:
            self.columns.append(column_name)

    fake_op = FakeOperations()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.downgrade()

    assert fake_op.columns == ["derived_context_version", "derived_context_text"]
