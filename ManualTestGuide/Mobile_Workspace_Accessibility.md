# Mobile Workspace Accessibility — Browser Verification

This guide verifies the accessible mobile workspace drawer introduced by the
`harden-mobile-workspace-accessibility` change. It is a browser UI check; no Swagger
request is required because no API contract changes.

## Prerequisites

1. From `Meridian/`, run `make dev-api` and `make dev-web`.
2. Sign in at `http://localhost:3000/`.
3. In browser developer tools, use a 375 px wide device viewport. Repeat the key
   composer check with the mobile on-screen keyboard visible if the browser/device supports it.

## Drawer lifecycle

1. On `/new`, activate **Open workspace navigation**.
2. Confirm the drawer is modal: keyboard focus starts on **Meridian new chat** and Tab cycles only
   among drawer controls.
3. Press Escape. Confirm the drawer closes and focus returns to **Open workspace navigation**.
4. Reopen the drawer and activate its close button. Confirm the same close and focus-restoration
   behavior.
5. Reopen the drawer and tap/click its dimmed backdrop. Confirm it closes without page navigation.
6. Reopen the drawer, open the signed-in email menu, and press Escape once. Confirm the account menu
   closes while the drawer remains open; press Escape again and confirm the drawer closes.

## Navigation and viewport checks

1. Reopen the drawer and choose Meridian/New chat, Chat, Documents, and Collections in turn.
2. Confirm each selection closes the drawer and reaches `/new`, `/chat`, `/documents`, or
   `/collections` respectively.
3. Confirm the desktop sidebar remains unchanged at desktop width.
4. At 375 px, verify no horizontal page overflow occurs on each destination.
5. Open a conversation and focus the composer. With the on-screen keyboard visible, confirm the
   drawer can still be closed/opened and the composer remains reachable.

## Completion checklist

- [ ] Drawer focus starts inside the modal and cannot escape with Tab or Shift+Tab.
- [ ] Escape, close control, and backdrop close the drawer safely.
- [ ] Escape returns focus to the opener when no navigation occurs.
- [ ] Every drawer destination closes the drawer and navigates correctly.
- [ ] Narrow and keyboard-reduced viewports have no horizontal overflow.
- [ ] Desktop sidebar behavior is unchanged.
