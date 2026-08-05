import uuid

import pytest

from app.services.lexical_retrieval import retrieve_lexical_candidates


class _Result:
    def __init__(self, rows) -> None:
        self.rows = rows

    def all(self):
        return self.rows


class _Session:
    def __init__(self, rows) -> None:
        self.rows = rows
        self.statements = []

    async def execute(self, statement):
        self.statements.append(statement)
        return _Result(self.rows if len(self.statements) == 2 else [])


@pytest.mark.asyncio
async def test_lexical_retrieval_is_bounded_and_ranks_rows() -> None:
    document_id, chunk_id = uuid.uuid4(), uuid.uuid4()
    session = _Session([(chunk_id, document_id, 3, 0.8)])

    candidates = await retrieve_lexical_candidates(
        session,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        query="TRV-104",
        collection_ids=[],
        limit=36,
    )

    assert len(session.statements) == 2
    assert candidates[0].chunk_id == chunk_id
    assert candidates[0].generation == 3
    assert candidates[0].rank == 1
    assert candidates[0].channel == "lexical"


@pytest.mark.asyncio
async def test_empty_lexical_query_does_not_query_database() -> None:
    session = _Session([])

    assert (
        await retrieve_lexical_candidates(
            session,  # type: ignore[arg-type]
            user_id=uuid.uuid4(),
            query=";;;",
            collection_ids=[],
            limit=36,
        )
        == []
    )
    assert session.statements == []
