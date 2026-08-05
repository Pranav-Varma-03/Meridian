"""Feature-gated reranking contract over lifecycle-valid source evidence."""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from app.services.retrieval import RetrievedSource


class Reranker(Protocol):
    async def rerank(
        self, *, query: str, sources: list[RetrievedSource]
    ) -> list[str]: ...


async def apply_reranker(
    *,
    reranker: Reranker,
    query: str,
    sources: list[RetrievedSource],
) -> list[RetrievedSource]:
    """Reorder only already-hydrated exact source rows; ignore bad IDs safely."""
    ordered_ids = await reranker.rerank(query=query, sources=sources)
    by_id = {source.chunk_id: source for source in sources}
    selected = [by_id[chunk_id] for chunk_id in ordered_ids if chunk_id in by_id]
    selected_ids = {source.chunk_id for source in selected}
    return [
        *selected,
        *(source for source in sources if source.chunk_id not in selected_ids),
    ]
