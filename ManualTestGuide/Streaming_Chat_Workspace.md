# Streaming Chat Workspace — Manual Test Guide

## Prerequisites

1. Start `make dev-api`, `make dev-worker`, and `make dev-web` from `Meridian/`.
2. Sign in at `http://localhost:3000/` and upload at least one document. Wait until it is ready.
3. For API-only checks, open `http://localhost:8000/docs`, authorize with an Auth0 Meridian API access token, and use the documented chat endpoints.

## New and streaming chat

1. Open `/chat`; select **New chat** and leave the scope as **All documents**.
2. Send a grounded question. Confirm your turn appears immediately and the assistant text grows while the request is open.
   - Verify Meridian answers render Markdown rather than displaying Markdown markers literally: headings,
     lists, bold/italic text, links, tables, quotes, and inline or fenced code should be formatted.
   - Raw HTML returned by the model must not become executable or rendered page markup.
3. Select **Sources** after completion. Confirm a right-side Sources pane opens for that exact answer.
   - Each citation starts collapsed and shows its filename, page when available, and section heading when available.
   - Expand two citations and confirm both stored excerpts remain visible for comparison. Citation excerpts are plain text, not rendered Markdown or HTML.
   - Select **Sources** on another answer. The pane updates to that answer's source list without another chat request. Select Sources again on the active answer, use the close button, or press Escape to close it.
   - Reopen an older conversation and repeat the check. Its citations must be the saved evidence snapshot; if a source is marked no longer active, its historical excerpt remains visible with that status.
   - On a narrow viewport, confirm Sources opens as a right-side modal drawer. Focus enters the drawer, Tab stays within it, and closing returns focus to the Sources control.
4. Ask an unsupported question. If the backend returns an empty source list, confirm the completed grounded response says that evidence was insufficient rather than presenting an error.
5. Stop a live response. Confirm the provisional answer is marked incomplete and the question can be placed back in the composer through retry feedback.

## Collections and history

1. Add one or more collections in **Retrieval scope**. Confirm chips appear; remove one and use **Clear to all documents**.
2. Send a question with selected collections, then reload and reopen the conversation. Confirm the saved selected scope returns.
3. Change scope in an existing conversation and send a new turn. Confirm the scope-change notice appears before the affected user turn.
4. Create more than ten conversations and confirm sidebar pagination works. Open an older item and verify its stored messages and citations hydrate.
5. Delete a conversation only after confirming the browser prompt. Confirm it leaves history and the workspace returns to a new-chat state.

## Swagger checks and negative cases

- `POST /api/v1/chat` with `retrieval_scope: {"mode":"all"}` streams `text`, `sources`, then `done`.
- Continue a conversation by sending only `conversation_id`; scope remains unchanged.
- Use an unknown collection ID or invalid scope shape: expect `404` or `422`.
- Omit bearer auth: expect `401`; exceed the chat limit: expect `429` with `Retry-After`.
