"use client";

import { useRef, useState } from "react";

import { ChatSidebar } from "@/components/chat-sidebar";
import type { WorkspaceCapabilities } from "@/lib/server/capabilities";

export function WorkspaceShell({
  children,
  email,
  capabilities,
}: {
  children: React.ReactNode;
  email: string | null | undefined;
  capabilities: WorkspaceCapabilities;
}) {
  const [mobileOpen, setMobileOpen] = useState(false);
  const mobileOpener = useRef<HTMLButtonElement>(null);

  function closeMobileNavigation(restoreFocus = true) {
    setMobileOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => mobileOpener.current?.focus());
    }
  }

  return (
    <div className="h-dvh overflow-hidden bg-background text-foreground">
      <div className="mx-auto flex h-full min-h-0 max-w-screen-2xl">
        <ChatSidebar capabilities={capabilities} email={email} />
        <button
          aria-label="Open workspace navigation"
          className="fixed left-3 top-3 z-10 rounded border border-border bg-card p-2 shadow-sm md:hidden"
          onClick={() => setMobileOpen(true)}
          ref={mobileOpener}
          type="button"
        >
          ☰
        </button>
        {mobileOpen ? (
          <>
            <div
              aria-hidden="true"
              className="fixed inset-0 z-20 bg-black/30 md:hidden"
              onClick={() => closeMobileNavigation()}
            />
            <ChatSidebar
              capabilities={capabilities}
              email={email}
              mobile
              onClose={() => closeMobileNavigation()}
              onNavigate={() => closeMobileNavigation(false)}
            />
          </>
        ) : null}
        <main className="min-h-0 min-w-0 flex-1 overflow-y-auto">{children}</main>
      </div>
    </div>
  );
}
