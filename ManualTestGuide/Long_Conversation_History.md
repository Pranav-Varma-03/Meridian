# Long Conversation History — Swagger and Browser Verification

## Prerequisites

Run `make dev-api` and `make dev-web` from `Meridian/`, then authenticate in Swagger at
`http://localhost:8000/docs`. Use a conversation with more than 50 messages.

## Swagger

1. Call `GET /api/v1/chat/conversations/{conversation_id}` without query parameters. Confirm the
   legacy full-history response remains available.
2. Call it with `message_limit=50`. Confirm `messages` contains the newest page in chronological
   order and the response includes `has_more_messages` and `next_before_sequence`.
3. When `has_more_messages` is true, call again with the same `message_limit` and
   `before_sequence=next_before_sequence`. Confirm the returned messages precede the first page
   and remain chronological.
4. Use another user's conversation ID. Confirm the endpoint returns `404` without ownership detail.

## Browser

1. Open the same conversation at `/chat/<conversation_id>`.
2. Confirm the newest messages load first and **Load older messages** appears when more history is
   available.
3. Scroll to a message, load older messages, and confirm the previously visible message remains in
   the same screen position.
4. Start a new turn after loading older messages. Confirm streamed output remains at the newest end
   and **Jump to latest** remains available when reading older content.

## Completion checklist

- [ ] Legacy full detail remains compatible.
- [ ] Cursor pages are owner-scoped, chronological, and include citation/scope data.
- [ ] Prepending older turns preserves the reading position.
- [ ] New streamed content remains at the newest end.
