# Web Loading Feedback — Browser Verification

1. Run `make dev-web` from `Meridian/` and sign in.
2. Throttle the browser network, then open Chats, Documents, Collections, and a conversation. Confirm each view keeps the workspace shell visible and uses list/transcript-shaped placeholders.
3. Change pages in a list. Confirm the current rows remain visible, the paging controls show loading, and repeated page clicks are prevented until the request completes.
4. Use keyboard navigation while a page refreshes. Confirm focus does not move and status feedback remains non-disruptive.
5. Enable `prefers-reduced-motion` in browser rendering settings. Confirm placeholders remain understandable without relying on animation.
