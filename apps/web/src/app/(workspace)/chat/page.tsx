import Link from "next/link";

import { EmptyState } from "@/components/app-feedback";

export default function ChatPage() {
  return (
    <section className="mx-auto flex min-h-screen max-w-4xl flex-col px-4 py-8 sm:px-8">
      <p className="text-sm font-medium text-primary">Workspace</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Chat with your documents</h1>
      <p className="mt-3 max-w-2xl text-muted-foreground">
        Ask grounded questions across all of your ready documents, or focus a conversation on collections.
      </p>
      <div className="mt-10">
        <EmptyState title="Your chat workspace is ready">
          Upload documents before starting a grounded conversation. <Link className="underline underline-offset-4" href="/documents">Open documents</Link>
        </EmptyState>
      </div>
    </section>
  );
}
