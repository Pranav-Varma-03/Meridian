# Web Product Quality — Authenticated Browser Verification

## Prerequisites

1. Use current Chromium/Chrome for the automated baseline. Check Firefox and Safari manually when releasing.
2. Run `make dev-api`, `make dev-worker`, and `make dev-web` from `Meridian/`.
3. Sign in at `http://localhost:3000/` with a Meridian user. Ensure one ready document exists.

## Checklist

- [ ] Select Meridian or New chat in the sidebar and verify `/new` shows the centered new-chat composer.
- [ ] Select Chat and verify `/chat` lists the complete paginated conversation history; open a row and verify `/chat/<conversation_id>` reloads the same conversation.
- [ ] Open a long conversation and verify its transcript scrolls independently while the scope control and composer remain visible. Scroll upward during streaming, confirm reading position remains stable, then use Jump to latest.
- [ ] Use the workspace-sidebar collapse control, reload, and verify the selected sidebar width persists. Switch among Chat, Documents, and Collections and verify their sidebar links remain functional. At narrow widths, verify the sidebar drawer remains reachable without horizontal overflow.
- [ ] Populate enough Recent conversations to exceed the sidebar height and verify only the sidebar middle region scrolls while the email/profile control remains visible.
- [ ] Open the email menu and verify it shows only the email, known Meridian permissions (if any), and Log out. Press Escape to close it.
- [ ] At 375 px, navigate Chat, Documents, and Collections without horizontal page overflow.
- [ ] Tab through navigation, upload, collection, chat, scope, source, and delete controls. Confirm focus remains visible.
- [ ] Change the theme to Light, Dark, then System; reload after each and confirm it persists.
- [ ] Upload a valid document and verify queued/processing/ready feedback. Try an invalid file and confirm safe feedback.
- [ ] Delete a document and confirm the dialog can be closed with Escape and returns focus to its trigger.
- [ ] Start a chat and confirm the live region announces start, completion, or failure without reading each token.
- [ ] Change collections, send a turn, reload the conversation, and confirm scope and scope timeline restore.
- [ ] Expand source cards and verify title, page, excerpt, and score. Confirm empty sources are a completed insufficiency state.
- [ ] Simulate 401, 403, 404, 422, 429, and 503 responses. Confirm safe feedback, retry timing/action, and preserved input/cache state.

## Completion

Record the tested browser/version, Auth0 tenant, API URL, and whether the live provider smoke path completed.
