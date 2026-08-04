"""Versioned, immutable configuration captured by each ingestion generation."""

from typing import Any

from app.core.config import Settings


def build_generation_configuration(settings: Settings) -> dict[str, Any]:
    """Return only deterministic processing settings, never credentials or source text."""
    return {
        "parser": {
            "provider": settings.document_parser_provider,
            "fallback_provider": settings.document_parser_fallback_provider,
            "version": settings.document_parser_version,
        },
        "tokenizer": {"name": settings.ingestion_tokenizer_version},
        "chunker": {
            "strategy": settings.chunk_strategy_version,
            "child_target_tokens": settings.chunk_child_target_tokens,
            "child_max_tokens": settings.chunk_child_max_tokens,
            "child_overlap_tokens": settings.chunk_child_overlap_tokens,
            "parent_target_tokens": settings.chunk_parent_target_tokens,
            "parent_max_tokens": settings.chunk_parent_max_tokens,
        },
        "embedding_text": {"version": settings.embedding_text_version},
        "lexical": {
            "backend": settings.lexical_backend,
            "version": settings.lexical_index_version,
        },
        "dense_index": {
            "provider": settings.embedding_provider,
            "model": settings.embedding_model,
            "version": settings.dense_index_version,
        },
        "fusion": {
            "version": settings.retrieval_fusion_version,
            "rrf_k": settings.retrieval_rrf_k,
            "dense_weight": settings.retrieval_dense_weight,
            "lexical_weight": settings.retrieval_lexical_weight,
        },
        "reranker": {
            "enabled": settings.reranking_enabled,
            "shadow": settings.reranking_shadow_enabled,
            "version": settings.reranker_version,
        },
        "prompt_policy": {"version": settings.prompt_policy_version},
    }
