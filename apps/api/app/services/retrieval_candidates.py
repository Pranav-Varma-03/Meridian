"""Provider-neutral retrieval candidates and deterministic rank fusion."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Literal

Channel = Literal["dense", "lexical"]


@dataclass(frozen=True, slots=True)
class RetrievalCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    generation: int
    channel: Channel
    rank: int
    score: float
    metadata: dict[str, str | int | float | bool] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class FusedCandidate:
    chunk_id: uuid.UUID
    document_id: uuid.UUID
    generation: int
    score: float
    dense_rank: int | None
    lexical_rank: int | None


def normalize_lexical_query(query: str) -> str:
    """Produce safe plain-tsquery input while preserving identifier components."""
    normalized = re.sub(r"[^\w]+", " ", query.casefold(), flags=re.UNICODE)
    return " ".join(part for part in normalized.split() if part)


def fuse_ranked_candidates(
    candidates: list[RetrievalCandidate],
    *,
    rrf_k: int,  # 60
    dense_weight: float,
    lexical_weight: float,
) -> list[FusedCandidate]:
    if rrf_k <= 0:
        raise ValueError("rrf_k must be positive")
    grouped: dict[uuid.UUID, list[RetrievalCandidate]] = {}
    for candidate in candidates:
        if candidate.rank <= 0 or candidate.generation <= 0:
            continue
        grouped.setdefault(candidate.chunk_id, []).append(candidate)

    fused: list[FusedCandidate] = []
    for chunk_id, entries in grouped.items():
        document_id = entries[0].document_id
        generation = entries[0].generation
        if any(
            entry.document_id != document_id or entry.generation != generation
            for entry in entries
        ):
            continue
        dense_rank = min(
            (entry.rank for entry in entries if entry.channel == "dense"), default=None
        )
        lexical_rank = min(
            (entry.rank for entry in entries if entry.channel == "lexical"),
            default=None,
        )
        score = 0.0
        if dense_rank is not None:
            score += dense_weight / (rrf_k + dense_rank)
        if lexical_rank is not None:
            score += lexical_weight / (rrf_k + lexical_rank)
        fused.append(
            FusedCandidate(
                chunk_id=chunk_id,
                document_id=document_id,
                generation=generation,
                score=score,
                dense_rank=dense_rank,
                lexical_rank=lexical_rank,
            )
        )
    return sorted(
        fused,
        key=lambda candidate: (
            -candidate.score,
            str(candidate.document_id),
            str(candidate.chunk_id),
        ),
    )
