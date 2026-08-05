import uuid

import pytest

from app.services.reranking import apply_reranker
from app.services.retrieval import RetrievedSource


def _source(label: str) -> RetrievedSource:
    return RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=label,
        filename="policy.txt",
        chunk_text=f"exact {label}",
        score=0.5,
        page_number=1,
        section_heading=None,
    )


@pytest.mark.asyncio
async def test_reranker_can_only_reorder_hydrated_sources() -> None:
    first, second = _source("first"), _source("second")

    class Reranker:
        async def rerank(self, *, query, sources):
            _ = query, sources
            return ["unknown", "second"]

    result = await apply_reranker(
        reranker=Reranker(), query="question", sources=[first, second]
    )

    assert result == [second, first]
