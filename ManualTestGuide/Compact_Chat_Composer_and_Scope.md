# Compact chat composer and retrieval scope

Use this browser checklist after starting `make dev-api`, `make dev-worker`, and `make dev-web`
from `Meridian/`. Sign in with an account that has at least two ready collections and one ready
document in each collection.

## New chat and compact entry

1. Open `http://localhost:3000/new`.
   - The Meridian landing/tagline is visible only on this new-chat route.
   - There is no large retrieval-scope panel above the composer.
   - The bottom entry is a compact multiline bar with a circular upward-arrow send control and a
     separate circular scope-icon control.
2. Enter a multi-line question.
   - The entry grows only as needed, up to its bounded height, then its contents scroll internally.
   - The send control remains compact, has a visible focus ring, and exposes `Send message` in the
     browser accessibility tree.
3. Send the question.
   - During retrieval/streaming, entry and scope editing are disabled and **Stop** remains usable.
   - When the response completes, entry and scope editing are restored.

## Scope overlay

1. Select the circular scope icon beside the composer.
   - Desktop: the panel opens above the composer without obscuring the transcript.
   - Narrow viewport: it opens as a constrained bottom sheet; only the sheet scrolls when needed.
   - It states `All documents` or the selected collection count.
2. Choose a collection from **Add collection…**.
   - A removable collection chip appears and the icon shows its selected-count badge.
3. Add a second collection, remove one chip, then choose **Clear to all documents**.
   - The panel returns to `All ready documents are included.`
   - Send a question after each scope choice as needed; the next chat request is the point where the
     local scope becomes the conversation's durable server scope.
4. With the panel open, press Escape and then tab.
   - The panel closes and keyboard focus returns to the scope icon.
5. Open a conversation at `/chat/<conversation-id>`.
   - The conversation title/header is absent; the transcript starts directly with User/Meridian
     message cards.
   - The existing conversation's saved scope is visible through the scope icon and overlay.

## Negative and completion checks

- Throttle or fail the collections request in browser DevTools: the scope icon is disabled and
  announces loading/unavailable collection choices; chat entry remains disabled rather than using an
  ambiguous scope.
- Start streaming, open no additional scope controls, and verify scope editing cannot be triggered
  until the stream ends or is stopped.
- Verify the page itself does not become the transcript scroll region: long conversation history
  scrolls independently while the compact composer stays visible.

Completion checklist:

- [ ] Compact composer, arrow send, and scope icon are keyboard accessible.
- [ ] Scope add/remove/clear works and persists on the next submitted message.
- [ ] Streaming and collection-loading guards work.
- [ ] Escape and outside-click dismiss the scope control without losing focus context.
- [ ] Conversation details are title-free and retain their existing message cards.
