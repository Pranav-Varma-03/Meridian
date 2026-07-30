"use client";

import type { ConversationSummary } from "@meridian/shared";
import Link from "next/link";
import useSWR from "swr";

import { ApiFeedback, EmptyState, LoadingState } from "@/components/app-feedback";
import { Pagination } from "@/components/pagination";
import { meridianKeys, meridianRequest } from "@/lib/api/client";
import { useState } from "react";

const PAGE_SIZE = 20;

export function ChatsIndex() {
  const [page, setPage] = useState(1);
  const history = useSWR<{ conversations: ConversationSummary[]; total: number }>(
    `${meridianKeys.conversations}?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`,
    meridianRequest
  );
  return (
    <section className="mx-auto min-h-full max-w-6xl px-4 py-8 sm:px-8">
      <header className="flex flex-wrap items-center justify-between gap-4">
        <div>
          <p className="text-sm font-medium text-primary">Meridian</p>
          <h1 className="mt-1 text-3xl font-semibold tracking-tight">Chats</h1>
        </div>
        <Link className="rounded-xl bg-primary px-4 py-2 text-primary-foreground" href="/new">
          New chat
        </Link>
      </header>
      <div className="mt-8">
        {history.isLoading ? (
          <LoadingState label="Loading chats…" />
        ) : history.error ? (
          <ApiFeedback error={history.error} onRetry={() => void history.mutate()} />
        ) : !history.data?.conversations.length ? (
          <EmptyState title="No conversations yet">
            Start a new grounded conversation when you are ready.
          </EmptyState>
        ) : (
          <>
            <ul className="divide-y divide-border">
              {history.data.conversations.map((conversation) => (
                <li key={conversation.id}>
                  <Link
                    className="flex min-h-16 items-center justify-between gap-4 py-4 hover:text-primary"
                    href={`/chat/${conversation.id}`}
                  >
                    <span className="min-w-0 truncate font-medium">
                      {conversation.title ?? "Untitled conversation"}
                    </span>
                    <time
                      className="shrink-0 text-sm text-muted-foreground"
                      dateTime={conversation.updated_at}
                    >
                      {new Date(conversation.updated_at).toLocaleDateString()}
                    </time>
                  </Link>
                </li>
              ))}
            </ul>
            <Pagination
              currentPage={page}
              onPageChange={setPage}
              pageSize={PAGE_SIZE}
              total={history.data.total}
            />
          </>
        )}
      </div>
    </section>
  );
}
