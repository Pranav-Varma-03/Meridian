# Chat loading and streaming feedback

Use this browser checklist after starting `make dev-api`, `make dev-worker`, and `make dev-web`.
Sign in with an account that has at least one ready document.

## Conversation and scope loading

1. Open a conversation that has not yet been viewed after a hard refresh.
   - The sidebar and page frame remain visible.
   - The message area shows a transcript-shaped loading skeleton, and the composer remains in its
     normal bottom position but is disabled until conversation data resolves.
2. Open **New chat** while collections are loading (throttle the network in browser DevTools).
   - The composer placeholder says `Loading available collections…` and the circular scope control
     is disabled with the accessible label `Retrieval scope: loading collection choices`.
   - Adding or removing collection scope is disabled until choices resolve.
   - If the collection request fails, the scope control identifies that collection choices are
     unavailable; chat entry remains disabled instead of silently using an ambiguous scope.

## Streaming lifecycle

1. Send a question grounded in a ready document.
   - Your message and a Meridian bubble appear immediately.
   - Before text arrives, the assistant bubble says `Searching your documents…`, the circular
     arrow Send control and scope control are disabled, and Stop is available.
   - When text begins, the same assistant bubble receives streamed content. There is no fake
     percentage or global spinner.
   - At completion, entry is restored and a screen-reader status announces completion once.
2. Click **Stop** before completion.
   - Entry is restored, the assistant message is labelled `stopped`, and **Retry last question**
     restores the submitted question to the composer.
3. To test an error, temporarily interrupt the API or network after sending.
   - The assistant message is labelled `incomplete`.
   - The error panel and **Retry last question** remain available; choosing retry restores the
     original query without duplicating the prior request.
4. Verify with a screen reader or browser accessibility tree that only phase changes are announced:
   searching, streaming, completed, stopped, or failed. Individual stream tokens must not be live
   announced.

## Completion checklist

- [ ] Detail loading retains a transcript shape and composer placement.
- [ ] Scope loading/unavailable states are visible and prevent edits.
- [ ] The provisional assistant response appears before first text and transitions in place.
- [ ] Stop and failed paths preserve a retryable query.
- [ ] Completion restores entry controls and announces one concise status.
