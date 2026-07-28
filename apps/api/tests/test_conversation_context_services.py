import types
import uuid

import pytest

from app.core.config import get_settings
from app.models.entities import MessageRole
from app.services import conversation_context, conversations


class _Rows:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows


class _CitationSession:
    async def execute(self, _statement):
        return _Rows(self.rows)

    def __init__(self, rows):
        self.rows = rows


class _OrderingSession:
    def __init__(self, conversation, last_sequence):
        self.conversation = conversation
        self.last_sequence = last_sequence
        self.scalar_calls = 0
        self.added = []

    async def scalar(self, _statement):
        self.scalar_calls += 1
        return self.conversation if self.scalar_calls == 1 else self.last_sequence

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None


class _SummarySession:
    async def scalar(self, _statement):
        return 12


@pytest.mark.asyncio
async def test_message_sequence_is_allocated_after_locked_conversation() -> None:
    conversation = types.SimpleNamespace(id=uuid.uuid4(), updated_at=None)
    session = _OrderingSession(conversation, last_sequence=7)

    message = await conversations.add_message(
        session,  # type: ignore[arg-type]
        conversation=conversation,
        role=MessageRole.user,
        content="Keep this exact message",
    )

    assert message.sequence_number == 8
    assert message.content == "Keep this exact message"
    assert session.added == [message]


@pytest.mark.asyncio
async def test_historic_citations_are_annotated_without_mutating_snapshot() -> None:
    active_document = uuid.uuid4()
    inactive_document = uuid.uuid4()
    message = types.SimpleNamespace(
        id=uuid.uuid4(),
        citations={
            "sources": [
                {"document_id": str(active_document), "generation": 2, "excerpt": "A"},
                {
                    "document_id": str(inactive_document),
                    "generation": 1,
                    "excerpt": "B",
                },
            ]
        },
    )
    session = _CitationSession(rows=[(active_document, 2)])

    displayed = await conversations.citation_availability(
        session,  # type: ignore[arg-type]
        user_id=uuid.uuid4(),
        messages=[message],
    )

    sources = displayed[message.id]["sources"]
    assert sources[0]["available"] is True
    assert sources[1]["available"] is False
    assert sources[1]["unavailable_reason"] == "source_unavailable"
    assert "available" not in message.citations["sources"][0]


@pytest.mark.asyncio
async def test_successful_summary_advances_only_the_eligible_watermark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    memory = types.SimpleNamespace(
        summary_json={}, summary_version=0, summarized_through_sequence=0
    )
    conversation = types.SimpleNamespace(id=uuid.uuid4())
    compacted = [
        types.SimpleNamespace(role=types.SimpleNamespace(value="user"), content="old")
    ]

    async def _memory(*_args, **_kwargs):
        return memory

    async def _messages(*_args, **kwargs):
        assert kwargs["after_sequence"] == 0
        assert kwargs["through_sequence"] == 4
        return compacted

    async def _summary(**_kwargs):
        return {"user_goal": "Review the policy"}

    monkeypatch.setattr(conversations, "get_or_create_memory", _memory)
    monkeypatch.setattr(conversations, "load_messages_after_sequence", _messages)
    monkeypatch.setattr(conversation_context, "_generate_summary", _summary)

    result = await conversation_context.update_rolling_summary(
        _SummarySession(),  # type: ignore[arg-type]
        conversation=conversation,
        client=object(),  # type: ignore[arg-type]
        settings=get_settings(),
    )

    assert result is memory
    assert memory.summary_json == {"user_goal": "Review the policy"}
    assert memory.summary_version == 1
    assert memory.summarized_through_sequence == 4
