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
        / "0006_add_conversation_retrieval_scopes.py"
    )
    spec = importlib.util.spec_from_file_location("migration_0006", migration_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_upgrade_creates_retrieval_scope_enum_only_once(monkeypatch) -> None:
    migration = _load_migration()
    enum_instances: list[_FakeEnum] = []

    class _FakeEnum(sa.String):
        def __init__(self, *values: str, name: str, create_type: bool = True) -> None:
            super().__init__()
            self.values = values
            self.name = name
            self.create_type = create_type
            self.create_calls = 0

        def create(self, bind, checkfirst: bool) -> None:
            _ = (bind, checkfirst)
            self.create_calls += 1

    class _FakeOperations:
        def __init__(self) -> None:
            self.tables: list[tuple[str, tuple[sa.Column, ...]]] = []

        def get_bind(self) -> object:
            return object()

        def create_table(self, name: str, *columns: sa.Column) -> None:
            self.tables.append((name, columns))

        def create_index(self, *args, **kwargs) -> None:
            _ = (args, kwargs)

    def fake_enum(*values: str, **kwargs) -> _FakeEnum:
        enum = _FakeEnum(*values, **kwargs)
        enum_instances.append(enum)
        return enum

    fake_op = _FakeOperations()
    monkeypatch.setattr(migration.postgresql, "ENUM", fake_enum)
    monkeypatch.setattr(migration, "op", fake_op)

    migration.upgrade()

    assert len(enum_instances) == 2
    assert enum_instances[0].create_calls == 1
    assert enum_instances[1].create_type is False
    assert [table[0] for table in fake_op.tables] == [
        "conversation_retrieval_scopes",
        "conversation_scope_events",
    ]
