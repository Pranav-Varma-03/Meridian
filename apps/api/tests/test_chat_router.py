import types
import uuid
from datetime import UTC, datetime

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient

from app.core.auth import get_current_user
from app.core.config import get_settings
from app.core.database import get_db_session
from app.main import app
from app.models.entities import RetrievalScopeMode
from app.routers import chat as chat_router
from app.services import chat_generation, conversation_context, conversations, retrieval


@pytest_asyncio.fixture
async def api_client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://testserver") as client:
        yield client


class _Session:
    async def commit(self) -> None:
        return None


@pytest.fixture
def chat_dependencies(monkeypatch: pytest.MonkeyPatch):
    user = types.SimpleNamespace(id=uuid.uuid4())
    session = _Session()
    conversation = types.SimpleNamespace(id=uuid.uuid4(), title="Question")
    added = []

    async def _current_user():
        return user

    async def _session():
        yield session

    async def _create_or_get(*_args, **_kwargs):
        return conversation

    async def _history(*_args, **_kwargs):
        return []

    async def _memory(*_args, **_kwargs):
        return None

    async def _update_summary(*_args, **_kwargs):
        return None

    async def _add(*_args, **kwargs):
        added.append(kwargs)
        return types.SimpleNamespace(
            id=uuid.uuid4(),
            role=kwargs["role"],
            content=kwargs["content"],
            citations=kwargs.get("citations") or {},
            created_at=datetime.now(UTC),
        )

    async def _submit(*_args, **kwargs):
        added.append(
            {
                "role": types.SimpleNamespace(value="user"),
                "content": kwargs["content"],
            }
        )
        requested = kwargs["requested_scope"]
        scope = (
            conversations.EffectiveRetrievalScope(requested[0], requested[1], 1)
            if requested is not None
            else conversations.EffectiveRetrievalScope(RetrievalScopeMode.all, (), 0)
        )
        return (
            types.SimpleNamespace(
                id=uuid.uuid4(),
                sequence_number=1,
                role=types.SimpleNamespace(value="user"),
                content=kwargs["content"],
                citations={},
                created_at=datetime.now(UTC),
            ),
            scope,
        )

    app.dependency_overrides[get_current_user] = _current_user
    app.dependency_overrides[get_db_session] = _session
    app.state.pinecone = object()
    monkeypatch.setattr(conversations, "create_or_get_conversation", _create_or_get)
    monkeypatch.setattr(conversations, "load_recent_history", _history)
    monkeypatch.setattr(conversations, "get_memory", _memory)
    monkeypatch.setattr(conversations, "add_message", _add)
    monkeypatch.setattr(conversations, "submit_user_turn", _submit)
    monkeypatch.setattr(conversation_context, "update_rolling_summary", _update_summary)
    yield user, conversation, added
    app.dependency_overrides.clear()
    if hasattr(app.state, "pinecone"):
        del app.state.pinecone


@pytest.mark.asyncio
async def test_chat_streams_grounded_sources_and_persists_completion(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, conversation, added = chat_dependencies
    source = retrieval.RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=str(uuid.uuid4()),
        filename="handbook.pdf",
        chunk_text="The policy requires approval.",
        score=0.9,
        page_number=3,
        section_heading=None,
    )

    async def _retrieve(*_args, **kwargs):
        assert kwargs["user_id"] == user.id
        return [source]

    async def _stream(**_kwargs):
        yield "Approval "
        yield "is required."

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    monkeypatch.setattr(chat_generation, "stream_grounded_answer", _stream)

    response = await api_client.post(
        "/api/v1/chat", json={"query": "What is required?"}
    )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/event-stream")
    assert response.text.count('"type": "sources"') == 1
    assert response.text.count('"type": "done"') == 1
    assert str(conversation.id) in response.text
    assert [item["role"].value for item in added] == ["user", "assistant"]
    assert added[-1]["citations"]["sources"][0]["document_id"] == str(
        source.document_id
    )


@pytest.mark.asyncio
async def test_chat_builds_openrouter_client_for_generation(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = retrieval.RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=str(uuid.uuid4()),
        filename="handbook.pdf",
        chunk_text="The policy requires approval.",
        score=0.9,
        page_number=3,
        section_heading=None,
    )
    created_clients = []

    class _Client:
        def __init__(self, **kwargs):
            self.kwargs = kwargs
            created_clients.append(self)

    async def _retrieve(*_args, **_kwargs):
        return [source]

    async def _stream(**kwargs):
        assert kwargs["client"].kwargs == {
            "api_key": "test-openrouter-key",
            "base_url": "https://openrouter.ai/api/v1",
        }
        yield "Approval is required."

    monkeypatch.setattr(
        chat_router,
        "settings",
        get_settings().model_copy(
            update={
                "openai_api_key": None,
                "openrouter_api_key": "test-openrouter-key",
                "openrouter_base_url": "https://openrouter.ai/api/v1",
            }
        ),
    )
    monkeypatch.setattr(chat_router, "AsyncOpenAI", _Client)
    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    monkeypatch.setattr(chat_generation, "stream_grounded_answer", _stream)

    response = await api_client.post("/api/v1/chat", json={"query": "Question"})

    assert response.status_code == 200
    assert len(created_clients) == 1


@pytest.mark.asyncio
async def test_chat_empty_retrieval_returns_insufficiency_answer(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _retrieve(*_args, **_kwargs):
        return []

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)

    response = await api_client.post("/api/v1/chat", json={"query": "Unknown?"})

    assert response.status_code == 200
    assert chat_generation.INSUFFICIENT_CONTEXT_ANSWER in response.text
    assert '"content": []' in response.text


@pytest.mark.asyncio
async def test_chat_uses_explicit_collection_scope_and_reports_it(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collection_id = uuid.uuid4()

    async def _retrieve(*_args, **kwargs):
        assert kwargs["collection_ids"] == [collection_id]
        return []

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    response = await api_client.post(
        "/api/v1/chat",
        json={
            "query": "Question",
            "retrieval_scope": {
                "mode": "collections",
                "collection_ids": [str(collection_id)],
            },
        },
    )
    assert response.status_code == 200
    assert '"mode": "collections"' in response.text
    assert '"version": 1' in response.text


@pytest.mark.asyncio
async def test_chat_rejects_conflicting_scope_fields(
    api_client: AsyncClient, chat_dependencies
) -> None:
    response = await api_client.post(
        "/api/v1/chat",
        json={
            "query": "Question",
            "collection_ids": [str(uuid.uuid4())],
            "retrieval_scope": {"mode": "all", "collection_ids": []},
        },
    )
    assert response.status_code == 422


@pytest.mark.asyncio
async def test_chat_accepts_matching_scope_fields_in_different_order(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first, second = uuid.uuid4(), uuid.uuid4()
    expected = sorted([first, second], key=str)

    async def _retrieve(*_args, **kwargs):
        assert kwargs["collection_ids"] == expected
        return []

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    response = await api_client.post(
        "/api/v1/chat",
        json={
            "query": "Question",
            "collection_ids": [str(second), str(first)],
            "retrieval_scope": {
                "mode": "collections",
                "collection_ids": [str(first), str(second)],
            },
        },
    )
    assert response.status_code == 200


@pytest.mark.asyncio
async def test_chat_bypasses_provider_when_retrieved_evidence_cannot_fit(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = retrieval.RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=str(uuid.uuid4()),
        filename="oversized.pdf",
        chunk_text="evidence " * 10000,
        score=0.9,
        page_number=1,
        section_heading=None,
    )
    provider_called = False

    async def _retrieve(*_args, **_kwargs):
        return [source]

    async def _stream(**_kwargs):
        nonlocal provider_called
        provider_called = True
        yield "unreachable"

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    monkeypatch.setattr(chat_generation, "stream_grounded_answer", _stream)

    response = await api_client.post("/api/v1/chat", json={"query": "Question"})

    assert response.status_code == 200
    assert chat_generation.INSUFFICIENT_CONTEXT_ANSWER in response.text
    assert provider_called is False
    assert '"content": []' in response.text


@pytest.mark.asyncio
async def test_chat_citations_match_only_sources_included_in_prompt(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    oversized = retrieval.RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=str(uuid.uuid4()),
        filename="oversized.pdf",
        chunk_text="evidence " * 10000,
        score=0.99,
        page_number=1,
        section_heading=None,
    )
    included = retrieval.RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=str(uuid.uuid4()),
        filename="included.pdf",
        chunk_text="The handbook requires manager approval.",
        score=0.8,
        page_number=2,
        section_heading=None,
    )
    captured_prompt = []

    async def _retrieve(*_args, **_kwargs):
        return [oversized, included]

    async def _stream(**kwargs):
        captured_prompt.extend(kwargs["prompt_messages"])
        yield "Approval is required."

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    monkeypatch.setattr(chat_generation, "stream_grounded_answer", _stream)

    response = await api_client.post("/api/v1/chat", json={"query": "Question"})

    assert response.status_code == 200
    assert str(included.document_id) in response.text
    assert str(oversized.document_id) not in response.text
    assert "included.pdf" in captured_prompt[-1]["content"]
    assert "oversized.pdf" not in captured_prompt[-1]["content"]


@pytest.mark.asyncio
async def test_chat_provider_failure_does_not_persist_partial_assistant_turn(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _user, _conversation, added = chat_dependencies
    source = retrieval.RetrievedSource(
        document_id=uuid.uuid4(),
        generation=1,
        chunk_id=str(uuid.uuid4()),
        filename="handbook.pdf",
        chunk_text="Grounded text.",
        score=0.9,
        page_number=None,
        section_heading=None,
    )

    async def _retrieve(*_args, **_kwargs):
        return [source]

    async def _stream(**_kwargs):
        raise chat_generation.GenerationUnavailableError("provider failure")
        yield "unreachable"  # pragma: no cover

    async def _summary_must_not_run(*_args, **_kwargs):
        raise AssertionError("failed output must not advance conversation memory")

    monkeypatch.setattr(retrieval, "retrieve_sources", _retrieve)
    monkeypatch.setattr(chat_generation, "stream_grounded_answer", _stream)
    monkeypatch.setattr(
        conversation_context, "update_rolling_summary", _summary_must_not_run
    )

    response = await api_client.post("/api/v1/chat", json={"query": "Question"})

    assert response.status_code == 200
    assert '"type": "error"' in response.text
    assert response.text.count('"type": "done"') == 1
    assert [item["role"].value for item in added] == ["user"]


@pytest.mark.asyncio
async def test_conversation_routes_are_owner_scoped(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user, conversation, _added = chat_dependencies
    conversation.updated_at = datetime.now(UTC)
    message = types.SimpleNamespace(
        id=uuid.uuid4(),
        role=types.SimpleNamespace(value="assistant"),
        content="A grounded answer",
        citations={"sources": []},
        created_at=datetime.now(UTC),
    )

    async def _list(_session, *, user_id, limit, offset):
        assert user_id == user.id
        assert (limit, offset) == (20, 0)
        return [conversation], 1

    async def _detail(_session, *, user_id, conversation_id):
        assert user_id == user.id
        assert conversation_id == conversation.id
        return types.SimpleNamespace(
            conversation=conversation,
            messages=[message],
            display_citations={
                message.id: {
                    "sources": [
                        {
                            "document_id": str(uuid.uuid4()),
                            "generation": 1,
                            "available": False,
                            "unavailable_reason": "source_unavailable",
                        }
                    ]
                }
            },
            retrieval_scope=conversations.EffectiveRetrievalScope(
                RetrievalScopeMode.all, (), 0
            ),
            scope_events=[],
        )

    async def _scope(_session, *, conversation_id):
        assert conversation_id == conversation.id
        return conversations.EffectiveRetrievalScope(RetrievalScopeMode.all, (), 0)

    async def _delete(_session, *, user_id, conversation_id):
        assert user_id == user.id
        assert conversation_id == conversation.id

    monkeypatch.setattr(conversations, "list_conversations", _list)
    monkeypatch.setattr(conversations, "get_conversation_with_messages", _detail)
    monkeypatch.setattr(conversations, "delete_conversation", _delete)
    monkeypatch.setattr(conversations, "get_effective_retrieval_scope", _scope)

    listed = await api_client.get("/api/v1/chat/conversations")
    detailed = await api_client.get(f"/api/v1/chat/conversations/{conversation.id}")
    deleted = await api_client.delete(f"/api/v1/chat/conversations/{conversation.id}")

    assert listed.status_code == 200
    assert listed.json()["total"] == 1
    assert detailed.status_code == 200
    historic_citation = detailed.json()["messages"][0]["citations"]["sources"][0]
    assert historic_citation["available"] is False
    assert historic_citation["unavailable_reason"] == "source_unavailable"
    assert deleted.status_code == 200


@pytest.mark.asyncio
async def test_conversation_route_hides_other_users_conversation(
    api_client: AsyncClient,
    chat_dependencies,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _detail(*_args, **_kwargs):
        raise conversations.ConversationNotFoundError("Conversation not found")

    monkeypatch.setattr(conversations, "get_conversation_with_messages", _detail)

    response = await api_client.get(f"/api/v1/chat/conversations/{uuid.uuid4()}")

    assert response.status_code == 404
    assert response.json()["error"]["message"] == "Conversation not found"
