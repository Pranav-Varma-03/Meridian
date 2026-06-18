import types

import pytest

from app.services import contextual_chunking


class _DummyResponses:
    def __init__(self) -> None:
        self.calls: list[dict] = []

    async def create(self, **kwargs):
        self.calls.append(kwargs)
        return types.SimpleNamespace(output_text="short retrieval context")


class _DummyOpenAI:
    def __init__(self) -> None:
        self.responses = _DummyResponses()


@pytest.mark.asyncio
async def test_situate_chunk_with_openai_uses_expected_prompt_shape() -> None:
    client = _DummyOpenAI()

    result = await contextual_chunking.situate_chunk_with_openai(
        client,  # type: ignore[arg-type]
        document_text="Full document content",
        chunk_text="Specific chunk content",
        model="gpt-4o-mini",
    )

    assert result == "short retrieval context"
    assert len(client.responses.calls) == 1
    call = client.responses.calls[0]
    assert call["model"] == "gpt-4o-mini"
    assert call["temperature"] == 0.0
    content = call["input"][0]["content"]
    assert "<document>\nFull document content\n</document>" in content[0]["text"]
    assert "<chunk>\nSpecific chunk content\n</chunk>" in content[1]["text"]
