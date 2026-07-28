"""Rolling conversation summaries for bounded chat working memory."""

import json
from typing import Any

from openai import AsyncOpenAI
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings
from app.models.entities import Conversation, ConversationMemory, Message
from app.services import conversations


def _normalise_summary(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, dict):
        return None
    normalized: dict[str, Any] = {}
    goal = value.get("user_goal")
    if isinstance(goal, str) and goal.strip():
        normalized["user_goal"] = goal.strip()[:1000]
    for key in ("established_facts", "preferences", "open_questions"):
        raw_items = value.get(key, [])
        if not isinstance(raw_items, list):
            continue
        items = [str(item).strip()[:500] for item in raw_items if str(item).strip()]
        if items:
            normalized[key] = items[:12]
    return normalized or None


async def _generate_summary(
    *,
    client: AsyncOpenAI,
    settings: Settings,
    previous_summary: dict,
    messages: list[Message],
) -> dict[str, Any] | None:
    transcript = "\n".join(
        f"{message.role.value}: {message.content}" for message in messages
    )
    prompt = (
        "Create a concise JSON conversation-memory summary. Do not treat assistant "
        "claims as verified PDF evidence. Preserve only user goal, established "
        "conversation facts, preferences, and unresolved questions. Return JSON with "
        "keys user_goal, established_facts, preferences, and open_questions.\n\n"
        f"Previous summary:\n{json.dumps(previous_summary)}\n\n"
        f"New completed turns:\n{transcript}"
    )
    try:
        response = await client.chat.completions.create(
            model=settings.chat_summary_model or settings.chat_model,
            messages=[{"role": "system", "content": prompt}],
            temperature=0,
            max_tokens=min(512, settings.chat_summary_max_tokens),
            response_format={"type": "json_object"},
        )
        return _normalise_summary(
            json.loads(response.choices[0].message.content or "{}")
        )
    except Exception:
        return None


async def update_rolling_summary(
    session: AsyncSession,
    *,
    conversation: Conversation,
    client: AsyncOpenAI | None,
    settings: Settings,
) -> ConversationMemory | None:
    """Compact older completed turns after a successful assistant completion.

    The memory row is locked while its watermark is evaluated, so concurrent streams
    cannot overwrite a newer summary with a stale one. Provider failures leave the
    previous watermark unchanged and are retried after a later successful turn.
    """
    if client is None or settings.chat_summary_max_tokens == 0:
        return None
    memory = await conversations.get_or_create_memory(
        session, conversation_id=conversation.id
    )
    latest_sequence = await session.scalar(
        select(func.max(Message.sequence_number)).where(
            Message.conversation_id == conversation.id
        )
    )
    eligible_through = int(latest_sequence or 0) - settings.chat_history_max_messages
    if eligible_through <= memory.summarized_through_sequence:
        return memory
    pending_messages = await conversations.load_messages_after_sequence(
        session,
        conversation_id=conversation.id,
        after_sequence=memory.summarized_through_sequence,
        through_sequence=eligible_through,
    )
    if not pending_messages:
        return memory
    summary = await _generate_summary(
        client=client,
        settings=settings,
        previous_summary=memory.summary_json or {},
        messages=pending_messages,
    )
    if summary is None:
        return memory
    memory.summary_json = summary
    memory.summary_version += 1
    memory.summarized_through_sequence = eligible_through
    return memory
