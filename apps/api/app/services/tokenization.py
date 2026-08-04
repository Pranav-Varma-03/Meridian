"""Deterministic token counting and bounded splitting for ingestion."""

from __future__ import annotations

from dataclasses import dataclass

import tiktoken


class TokenizerConfigurationError(ValueError):
    """The persisted tokenizer or token bounds are unsupported."""


@dataclass(frozen=True, slots=True)
class Tokenizer:
    version: str
    _encoding: tiktoken.Encoding

    def count(self, text: str) -> int:
        return len(self._encoding.encode(text, disallowed_special=()))

    def split(self, text: str, *, maximum_tokens: int) -> list[str]:
        if maximum_tokens <= 0:
            raise TokenizerConfigurationError("maximum_tokens must be positive")
        tokens = self._encoding.encode(text, disallowed_special=())
        return [
            self._encoding.decode(tokens[index : index + maximum_tokens])
            for index in range(0, len(tokens), maximum_tokens)
        ]


def get_tokenizer(version: str) -> Tokenizer:
    if version != "cl100k_base":
        raise TokenizerConfigurationError(f"Unsupported ingestion tokenizer: {version}")
    return Tokenizer(version=version, _encoding=tiktoken.get_encoding(version))


def validate_chunk_bounds(
    *,
    child_target_tokens: int,
    child_max_tokens: int,
    child_overlap_tokens: int,
    parent_target_tokens: int,
    parent_max_tokens: int,
) -> None:
    if child_target_tokens <= 0 or child_max_tokens <= 0:
        raise TokenizerConfigurationError("Child token bounds must be positive")
    if child_target_tokens > child_max_tokens:
        raise TokenizerConfigurationError("Child target must not exceed child maximum")
    if child_overlap_tokens < 0 or child_overlap_tokens >= child_max_tokens:
        raise TokenizerConfigurationError(
            "Child overlap must be non-negative and below the child maximum"
        )
    if parent_target_tokens <= 0 or parent_max_tokens <= 0:
        raise TokenizerConfigurationError("Parent token bounds must be positive")
    if parent_target_tokens > parent_max_tokens:
        raise TokenizerConfigurationError(
            "Parent target must not exceed parent maximum"
        )
