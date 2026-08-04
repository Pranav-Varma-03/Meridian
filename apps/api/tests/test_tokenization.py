import pytest

from app.services.tokenization import (
    TokenizerConfigurationError,
    get_tokenizer,
    validate_chunk_bounds,
)


def test_cl100k_tokenizer_counts_and_splits_without_exceeding_limit() -> None:
    tokenizer = get_tokenizer("cl100k_base")
    text = " ".join(f"identifier-{index}" for index in range(80))

    chunks = tokenizer.split(text, maximum_tokens=12)

    assert tokenizer.count(text) > 12
    assert chunks
    assert all(tokenizer.count(chunk) <= 12 for chunk in chunks)
    assert "".join(chunks) == text


def test_tokenizer_rejects_unknown_version_and_invalid_bounds() -> None:
    with pytest.raises(TokenizerConfigurationError, match="Unsupported"):
        get_tokenizer("provider-undocumented-v1")
    with pytest.raises(TokenizerConfigurationError, match="target"):
        validate_chunk_bounds(
            child_target_tokens=513,
            child_max_tokens=512,
            child_overlap_tokens=48,
            parent_target_tokens=900,
            parent_max_tokens=1200,
        )
