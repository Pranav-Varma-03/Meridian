from app.core.config import Settings
from app.services.ingestion_configuration import build_generation_configuration
from tests.helpers import set_required_env


def test_generation_configuration_captures_all_processing_versions(monkeypatch) -> None:
    set_required_env(monkeypatch)

    configuration = build_generation_configuration(Settings())

    assert configuration == {
        "parser": {
            "provider": "unstructured",
            "fallback_provider": "compatibility",
            "version": "unstructured_by_title_v1",
        },
        "tokenizer": {"name": "cl100k_base"},
        "chunker": {
            "strategy": "structure_aware_parent_child_v1",
            "child_target_tokens": 384,
            "child_max_tokens": 512,
            "child_overlap_tokens": 48,
            "parent_target_tokens": 900,
            "parent_max_tokens": 1200,
        },
        "embedding_text": {"version": "document_section_locator_v1"},
        "lexical": {"backend": "postgresql", "version": "postgres_simple_v1"},
        "dense_index": {
            "provider": "pinecone",
            "model": "llama-text-embed-v2",
            "version": "dense_child_v1",
        },
        "fusion": {
            "version": "weighted_rrf_v1",
            "rrf_k": 60,
            "dense_weight": 1.0,
            "lexical_weight": 1.0,
        },
        "reranker": {"enabled": False, "shadow": False, "version": "none_v1"},
        "prompt_policy": {"version": "source_only_v1"},
    }


def test_generation_configuration_is_independent_of_legacy_rows(monkeypatch) -> None:
    set_required_env(monkeypatch)

    configuration = build_generation_configuration(Settings())

    # Existing generations retain their historical empty configuration. New
    # generations capture a complete immutable snapshot instead of mutating it.
    assert {} != configuration
    assert configuration["chunker"]["strategy"] == "structure_aware_parent_child_v1"
