from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import sqlalchemy as sa


def _load_migration() -> ModuleType:
    migration_path = (
        Path(__file__).parents[1]
        / "alembic"
        / "versions"
        / "0007_add_parent_child_retrieval_state.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0007", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_adds_only_nullable_fields_to_legacy_chunks(monkeypatch) -> None:
    migration = _load_migration()

    class FakeOperations:
        def __init__(self) -> None:
            self.tables: list[str] = []
            self.columns: list[tuple[str, sa.Column]] = []
            self.indexes: list[tuple[str, str, list[str], dict]] = []

        def create_table(self, name: str, *columns: sa.Column, **kwargs) -> None:
            _ = (columns, kwargs)
            self.tables.append(name)

        def add_column(self, table_name: str, column: sa.Column) -> None:
            self.columns.append((table_name, column))

        def create_index(
            self, name: str, table_name: str, columns: list[str], **kwargs
        ) -> None:
            self.indexes.append((name, table_name, columns, kwargs))

    fake_op = FakeOperations()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    assert fake_op.tables == ["document_parent_windows"]
    assert all(table == "document_chunks" for table, _ in fake_op.columns)
    assert {column.name for _, column in fake_op.columns} >= {
        "parent_id",
        "previous_chunk_id",
        "next_chunk_id",
        "embedding_text",
        "section_path",
        "page_start",
        "page_end",
        "source_start",
        "source_end",
        "strategy_version",
        "lexical_search",
    }
    assert all(column.nullable for _, column in fake_op.columns)
    assert (
        "ix_chunks_lexical_search",
        "document_chunks",
        ["lexical_search"],
        {"postgresql_using": "gin"},
    ) in fake_op.indexes


def test_downgrade_removes_new_state_in_reverse_order(monkeypatch) -> None:
    migration = _load_migration()

    class FakeOperations:
        def __init__(self) -> None:
            self.calls: list[tuple[str, str]] = []

        def drop_index(self, name: str, **kwargs) -> None:
            _ = kwargs
            self.calls.append(("index", name))

        def drop_column(self, table_name: str, column_name: str) -> None:
            _ = table_name
            self.calls.append(("column", column_name))

        def drop_table(self, name: str) -> None:
            self.calls.append(("table", name))

    fake_op = FakeOperations()
    monkeypatch.setattr(migration, "op", fake_op)

    migration.downgrade()

    assert fake_op.calls[0] == ("index", "ix_chunks_lexical_search")
    assert fake_op.calls[-1] == ("table", "document_parent_windows")
