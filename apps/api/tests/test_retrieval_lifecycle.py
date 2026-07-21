import uuid

import pytest

from app.services.retrieval_lifecycle import filter_active_retrieval_candidates


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _Session:
    def __init__(self, rows):
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.rows)


@pytest.mark.asyncio
async def test_retrieval_guard_keeps_only_current_active_generation() -> None:
    user_id = uuid.uuid4()
    active_document_id = uuid.uuid4()
    stale_document_id = uuid.uuid4()
    session = _Session(rows=[(active_document_id, 2)])
    candidates = [
        {"metadata": {"document_id": str(active_document_id), "generation": 2}},
        {"metadata": {"document_id": str(active_document_id), "generation": 1}},
        {"metadata": {"document_id": str(stale_document_id), "generation": 1}},
    ]

    result = await filter_active_retrieval_candidates(
        session,  # type: ignore[arg-type]
        user_id=user_id,
        candidates=candidates,
    )

    assert result == [candidates[0]]
    assert len(session.statements) == 1


@pytest.mark.asyncio
async def test_retrieval_guard_drops_deleting_and_malformed_candidates() -> None:
    session = _Session(rows=[])
    candidates = [
        {"metadata": {"document_id": str(uuid.uuid4()), "generation": 1}},
        {"metadata": {"document_id": "not-a-uuid", "generation": 1}},
        {"metadata": {"document_id": str(uuid.uuid4()), "generation": 0}},
        {"metadata": {}},
    ]

    result = await filter_active_retrieval_candidates(
        session,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        candidates=candidates,
    )

    assert result == []
    assert len(session.statements) == 1
