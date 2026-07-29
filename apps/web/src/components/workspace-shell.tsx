"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import type { WorkspaceCapabilities } from "@/lib/server/capabilities";

const navigation = [
  { href: "/chat", label: "Chat" },
  { href: "/documents", label: "Documents" },
  { href: "/collections", label: "Collections" },
];

interface WorkspaceShellProps {
  children: React.ReactNode;
  email: string | null | undefined;
  capabilities: WorkspaceCapabilities;
}

export function WorkspaceShell({ children, email, capabilities }: WorkspaceShellProps) {
  const pathname = usePathname();

  return (
    <div className="min-h-screen bg-background text-foreground">
      <header className="border-b border-border bg-card md:hidden">
        <div className="flex min-h-16 items-center justify-between px-4">
          <Link className="font-semibold tracking-tight" href="/chat">
            Meridian
          </Link>
          <a className="text-sm text-muted-foreground underline-offset-4 hover:underline" href="/auth/logout">
            Log out
          </a>
        </div>
        <nav aria-label="Workspace" className="flex gap-1 overflow-x-auto px-3 pb-3">
          {navigation.map((item) => (
            <WorkspaceLink key={item.href} item={item} active={pathname === item.href} />
          ))}
        </nav>
      </header>

      <div className="mx-auto flex min-h-screen max-w-screen-2xl">
        <aside className="hidden w-64 shrink-0 border-r border-border bg-card p-4 md:flex md:flex-col">
          <Link className="px-3 py-2 text-lg font-semibold tracking-tight" href="/chat">
            Meridian
          </Link>
          <p className="px-3 pb-6 text-sm text-muted-foreground">Grounded document chat</p>
          <nav aria-label="Workspace" className="space-y-1">
            {navigation.map((item) => (
              <WorkspaceLink key={item.href} item={item} active={pathname === item.href} />
            ))}
          </nav>
          <div className="mt-auto border-t border-border pt-4">
            <p className="truncate px-3 text-sm text-muted-foreground">{email ?? "Signed in"}</p>
            {capabilities.canReingest ? (
              <p className="px-3 pt-1 text-xs text-muted-foreground">Re-ingestion enabled</p>
            ) : null}
            <a className="mt-3 block rounded-md px-3 py-2 text-sm hover:bg-muted" href="/auth/logout">
              Log out
            </a>
          </div>
        </aside>
        <main className="min-w-0 flex-1">{children}</main>
      </div>
    </div>
  );
}

function WorkspaceLink({
  item,
  active,
}: {
  item: (typeof navigation)[number];
  active: boolean;
}) {
  return (
    <Link
      aria-current={active ? "page" : undefined}
      className={`block rounded-md px-3 py-2 text-sm font-medium transition-colors ${
        active ? "bg-muted text-foreground" : "text-muted-foreground hover:bg-muted hover:text-foreground"
      }`}
      href={item.href}
    >
      {item.label}
    </Link>
  );
}
