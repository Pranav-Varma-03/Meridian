"use client";

import type { ConversationSummary } from "@meridian/shared";
import Link from "next/link";
import { usePathname } from "next/navigation";
import type { KeyboardEvent as ReactKeyboardEvent } from "react";
import { useEffect, useRef, useState } from "react";
import useSWR from "swr";

import { meridianKeys, meridianRequest } from "@/lib/api/client";
import type { WorkspaceCapabilities } from "@/lib/server/capabilities";

const key = `${meridianKeys.conversations}?limit=8&offset=0`;
const workspaceNavigation = [
  { href: "/chat", label: "Chat", icon: "◷" },
  { href: "/documents", label: "Documents", icon: "▤" },
  { href: "/collections", label: "Collections", icon: "◫" },
];

export function ChatSidebar({
  email,
  capabilities,
  mobile = false,
  onClose,
  onNavigate,
}: {
  email: string | null | undefined;
  capabilities: WorkspaceCapabilities;
  mobile?: boolean;
  onClose?: () => void;
  onNavigate?: () => void;
}) {
  const pathname = usePathname();
  const [collapsed, setCollapsed] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const accountTrigger = useRef<HTMLButtonElement>(null);
  const drawer = useRef<HTMLElement>(null);
  const wasOpen = useRef(false);
  const history = useSWR<{ conversations: ConversationSummary[]; total: number }>(
    key,
    meridianRequest
  );
  useEffect(() => {
    setCollapsed(window.localStorage.getItem("meridian-chat-sidebar") === "collapsed");
  }, []);
  useEffect(() => {
    if (mobile) return;
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape" && accountOpen) setAccountOpen(false);
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [accountOpen, mobile]);
  useEffect(() => {
    if (!mobile) return;
    const frame = window.requestAnimationFrame(() => firstFocusable(drawer.current)?.focus());
    return () => window.cancelAnimationFrame(frame);
  }, [mobile]);
  useEffect(() => {
    if (!accountOpen && wasOpen.current) accountTrigger.current?.focus();
    wasOpen.current = accountOpen;
  }, [accountOpen]);
  function toggle() {
    setCollapsed((value) => {
      const next = !value;
      window.localStorage.setItem("meridian-chat-sidebar", next ? "collapsed" : "expanded");
      return next;
    });
  }
  function handleDrawerKeyDown(event: ReactKeyboardEvent<HTMLElement>) {
    if (!mobile) return;
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (accountOpen) setAccountOpen(false);
      else onClose?.();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = focusableElements(drawer.current);
    if (!focusable.length) {
      event.preventDefault();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  }
  const closeForNavigation = mobile ? onNavigate : undefined;
  const size = mobile
    ? "fixed inset-y-0 left-0 z-30 w-72 p-3 shadow-xl"
    : collapsed
      ? "w-16 p-2"
      : "w-72 p-3";
  const compact = collapsed && !mobile;
  return (
    <aside
      className={`h-full min-h-0 shrink-0 border-r border-border bg-card flex flex-col ${mobile ? "md:hidden" : "hidden md:flex"} ${size}`}
      aria-label="Chat navigation"
      aria-modal={mobile || undefined}
      onKeyDown={handleDrawerKeyDown}
      ref={drawer}
      role={mobile ? "dialog" : undefined}
    >
      <div className="flex items-center justify-between gap-2">
        <Link
          aria-label="Meridian new chat"
          className="truncate rounded px-2 py-2 text-lg font-semibold"
          href="/new"
          onClick={closeForNavigation}
        >
          {compact ? "M" : "Meridian"}
        </Link>
        <button
          aria-label={
            mobile
              ? "Close chat navigation"
              : collapsed
                ? "Expand chat sidebar"
                : "Collapse chat sidebar"
          }
          className="rounded p-2 hover:bg-muted"
          onClick={mobile ? onClose : toggle}
          title={mobile ? "Close navigation" : collapsed ? "Expand sidebar" : "Collapse sidebar"}
          type="button"
        >
          ☰
        </button>
      </div>
      <Link
        aria-label="New chat"
        className="mt-4 rounded-lg bg-primary px-3 py-2 text-center text-sm text-primary-foreground"
        href="/new"
        onClick={closeForNavigation}
      >
        {compact ? "+" : "New chat"}
      </Link>
      <div className="min-h-0 flex-1 overflow-y-auto">
        <nav className="mt-3 space-y-1" aria-label="Workspace">
          {workspaceNavigation.map((item) => {
            const active =
              item.href === "/chat"
                ? pathname === "/new" || pathname.startsWith("/chat")
                : pathname === item.href;
            return (
              <Link
                aria-current={active ? "page" : undefined}
                aria-label={compact ? item.label : undefined}
                className={`block rounded px-2 py-2 text-sm ${active ? "bg-muted font-medium" : "hover:bg-muted"} ${compact ? "text-center" : ""}`}
                href={item.href}
                key={item.href}
                onClick={closeForNavigation}
                title={compact ? item.label : undefined}
              >
                {compact ? item.icon : item.label}
              </Link>
            );
          })}
        </nav>
        {!compact ? (
          <>
            <p className="mt-6 px-2 text-xs font-semibold uppercase tracking-wide text-muted-foreground">
              Recents
            </p>
            <nav className="mt-2 space-y-1" aria-label="Recent conversations">
              {history.data?.conversations.map((conversation) => (
                <Link
                  aria-current={pathname === `/chat/${conversation.id}` ? "page" : undefined}
                  className={`block truncate rounded px-2 py-2 text-sm ${pathname === `/chat/${conversation.id}` ? "bg-muted" : "hover:bg-muted"}`}
                  href={`/chat/${conversation.id}`}
                  key={conversation.id}
                  onClick={closeForNavigation}
                >
                  {conversation.title ?? "Untitled conversation"}
                </Link>
              ))}
              {history.data?.conversations.length ? (
                <Link
                  className="block px-2 py-2 text-sm text-muted-foreground underline"
                  href="/chat"
                  onClick={closeForNavigation}
                >
                  View all chats
                </Link>
              ) : null}
            </nav>
          </>
        ) : (
          <nav className="mt-4" aria-label="Recent conversations">
            <Link
              aria-label="All chats"
              className="block rounded p-2 text-center hover:bg-muted"
              href="/chat"
              onClick={closeForNavigation}
              title="All chats"
            >
              ◷
            </Link>
          </nav>
        )}
      </div>
      <div className="relative mt-auto">
        <button
          aria-expanded={accountOpen}
          aria-haspopup="menu"
          className="w-full truncate rounded px-2 py-2 text-left text-sm hover:bg-muted"
          onClick={() => setAccountOpen((value) => !value)}
          ref={accountTrigger}
          type="button"
        >
          {compact ? "@" : (email ?? "Signed in")}
        </button>
        {accountOpen ? (
          <div
            className="absolute bottom-full left-0 z-20 mb-2 w-64 rounded-lg border border-border bg-card p-3 shadow-lg"
            role="menu"
          >
            <p className="truncate text-sm font-medium">{email ?? "Signed in"}</p>
            <p className="mt-3 text-xs font-semibold uppercase text-muted-foreground">
              Permissions
            </p>
            {capabilities.permissions.length ? (
              capabilities.permissions.map((permission) => (
                <p className="mt-1 text-sm" key={permission}>
                  {permission}
                </p>
              ))
            ) : (
              <p className="mt-1 text-sm text-muted-foreground">No elevated permissions</p>
            )}
            <a
              className="mt-4 block rounded px-2 py-2 text-sm hover:bg-muted"
              href="/auth/logout"
              onClick={closeForNavigation}
              role="menuitem"
            >
              Log out
            </a>
          </div>
        ) : null}
      </div>
    </aside>
  );
}

function focusableElements(container: HTMLElement | null): HTMLElement[] {
  if (!container) return [];
  return Array.from(
    container.querySelectorAll<HTMLElement>(
      'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    )
  ).filter((element) => !element.hasAttribute("hidden"));
}

function firstFocusable(container: HTMLElement | null): HTMLElement | undefined {
  return focusableElements(container)[0];
}
