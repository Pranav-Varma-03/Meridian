import uuid

import pytest

from app.services.retrieval_candidates import (
    RetrievalCandidate,
    fuse_ranked_candidates,
    normalize_lexical_query,
)


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("TRV-104", "trv 104"),
        ('"INV-88219"', "inv 88219"),
        ("Clause 4.2, Meals!", "clause 4 2 meals"),
        ("MÉALS", "méals"),
        ("   ", ""),
        (";;;", ""),
    ],
)
def test_normalize_lexical_query_handles_identifiers_and_punctuation(
    query: str, expected: str
) -> None:
    assert normalize_lexical_query(query) == expected


def test_fusion_merges_duplicates_and_orders_deterministically() -> None:
    document_id = uuid.uuid4()
    shared_id = uuid.uuid4()
    lexical_only_id = uuid.uuid4()
    candidates = [
        RetrievalCandidate(shared_id, document_id, 2, "dense", 1, 0.9),
        RetrievalCandidate(shared_id, document_id, 2, "lexical", 3, 0.3),
        RetrievalCandidate(lexical_only_id, document_id, 2, "lexical", 1, 0.8),
    ]

    fused = fuse_ranked_candidates(
        candidates, rrf_k=60, dense_weight=1.0, lexical_weight=1.0
    )

    assert len(fused) == 2
    assert fused[0].chunk_id == shared_id
    assert fused[0].dense_rank == 1
    assert fused[0].lexical_rank == 3
    assert fused[1].chunk_id == lexical_only_id


def test_fusion_rejects_conflicting_identity_for_one_chunk() -> None:
    chunk_id = uuid.uuid4()
    candidates = [
        RetrievalCandidate(chunk_id, uuid.uuid4(), 1, "dense", 1, 0.9),
        RetrievalCandidate(chunk_id, uuid.uuid4(), 1, "lexical", 1, 0.9),
    ]

    assert (
        fuse_ranked_candidates(
            candidates, rrf_k=60, dense_weight=1.0, lexical_weight=1.0
        )
        == []
    )
