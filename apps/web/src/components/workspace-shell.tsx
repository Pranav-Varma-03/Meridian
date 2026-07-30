"use client";

import { useState } from "react";

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
  return (
    <div className="min-h-screen overflow-x-hidden bg-background text-foreground">
      <div className="mx-auto flex min-h-screen max-w-screen-2xl">
        <ChatSidebar capabilities={capabilities} email={email} />
        <button
          aria-label="Open workspace navigation"
          className="fixed left-3 top-3 z-10 rounded border border-border bg-card p-2 shadow-sm md:hidden"
          onClick={() => setMobileOpen(true)}
          type="button"
        >
          ☰
        </button>
        {mobileOpen ? (
          <>
            <button
              aria-label="Close chat navigation"
              className="fixed inset-0 z-20 bg-black/30 md:hidden"
              onClick={() => setMobileOpen(false)}
              type="button"
            />
            <ChatSidebar
              capabilities={capabilities}
              email={email}
              mobile
              onClose={() => setMobileOpen(false)}
            />
          </>
        ) : null}
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}
