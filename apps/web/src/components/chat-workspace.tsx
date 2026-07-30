"use client";

import type {
  CollectionListResponse,
  ConversationMessage,
  ConversationResponse,
  ConversationScopeEventResponse,
  RetrievalScopeRequest,
  RetrievalScopeResponse,
  SourceCitation,
} from "@meridian/shared";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import useSWR, { mutate as mutateCache } from "swr";

import { ApiFeedback, EmptyState, LoadingState } from "@/components/app-feedback";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { meridianKeys, meridianRequest } from "@/lib/api/client";
import { streamChat } from "@/lib/chat/client";

type LiveMessage = ConversationMessage & {
  provisional?: boolean;
  failed?: boolean;
  sources?: SourceCitation[];
};
const allScope: RetrievalScopeResponse = { mode: "all", collection_ids: [], version: 0 };

export function ChatWorkspace({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const [scope, setScope] = useState<RetrievalScopeResponse>(allScope);
  const [scopeDirty, setScopeDirty] = useState(false);
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [query, setQuery] = useState("");
  const [retryQuery, setRetryQuery] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [streamAnnouncement, setStreamAnnouncement] = useState("");
  const aborter = useRef<AbortController | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const detail = useSWR<ConversationResponse>(
    conversationId ? `/api/meridian/chat/conversations/${conversationId}` : null,
    meridianRequest
  );
  const collections = useSWR<CollectionListResponse>(
    `${meridianKeys.collections}?limit=100&offset=0`,
    meridianRequest
  );
  const hasLibrary =
    (collections.data?.collections.reduce(
      (count, collection) => count + collection.document_count,
      0
    ) ?? 0) > 0;
  const collectionNames = useMemo(
    () => new Map((collections.data?.collections ?? []).map((item) => [item.id, item.name])),
    [collections.data]
  );

  useEffect(() => {
    if (detail.data) {
      setMessages(detail.data.messages);
      setScope(detail.data.retrieval_scope);
      setScopeDirty(false);
    }
  }, [detail.data]);
  useEffect(() => () => aborter.current?.abort(), []);
  function preferredScope(): RetrievalScopeRequest {
    return scope.mode === "collections"
      ? { mode: "collections", collection_ids: scope.collection_ids }
      : { mode: "all" };
  }
  function setCollectionIds(ids: string[]) {
    setScope({
      mode: ids.length ? "collections" : "all",
      collection_ids: ids,
      version: scope.version,
    });
    setScopeDirty(true);
  }
  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = query.trim();
    if (!text || streaming) return;
    if (!hasLibrary) {
      setError(new Error("Upload a document before starting a grounded conversation."));
      return;
    }
    const assistantId = `assistant-${crypto.randomUUID()}`;
    const userId = `user-${crypto.randomUUID()}`;
    setMessages((current) => [
      ...current,
      {
        id: userId,
        role: "user",
        content: text,
        citations: {},
        created_at: new Date().toISOString(),
        provisional: true,
      },
      {
        id: assistantId,
        role: "assistant",
        content: "",
        citations: {},
        created_at: new Date().toISOString(),
        provisional: true,
      },
    ]);
    setQuery("");
    setRetryQuery(null);
    setError(null);
    setStreamAnnouncement("Meridian is generating a response.");
    setStreaming(true);
    const controller = new AbortController();
    aborter.current = controller;
    const request: {
      query: string;
      conversation_id?: string;
      retrieval_scope?: RetrievalScopeRequest;
    } = { query: text };
    if (conversationId) request.conversation_id = conversationId;
    if (!conversationId || scopeDirty) request.retrieval_scope = preferredScope();
    try {
      await streamChat(request, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "text")
            setMessages((current) =>
              current.map((item) =>
                item.id === assistantId ? { ...item, content: item.content + event.content } : item
              )
            );
          if (event.type === "sources")
            setMessages((current) =>
              current.map((item) =>
                item.id === assistantId
                  ? { ...item, sources: event.content, citations: { sources: event.content } }
                  : item
              )
            );
          if (event.type === "error") {
            setError(new Error(event.message));
            setStreamAnnouncement("Meridian could not complete the response.");
            setMessages((current) =>
              current.map((item) => (item.id === assistantId ? { ...item, failed: true } : item))
            );
          }
          if (event.type === "done") {
            setScope((current) =>
              event.retrieval_scope.version >= current.version ? event.retrieval_scope : current
            );
            setScopeDirty(false);
            setStreamAnnouncement("Meridian response complete.");
            setMessages((current) =>
              current.map((item) =>
                item.id === assistantId || item.id === userId
                  ? { ...item, provisional: false }
                  : item
              )
            );
            void mutateCache(
              (key) => typeof key === "string" && key.startsWith(meridianKeys.conversations)
            );
            if (!conversationId) router.replace(`/chat/${event.conversation_id}`);
          }
        },
      });
    } catch (reason) {
      if (!controller.signal.aborted) {
        setError(reason);
        setStreamAnnouncement(
          "Meridian could not complete the response. Your question is ready to retry."
        );
      }
      setMessages((current) =>
        current.map((item) => (item.id === assistantId ? { ...item, failed: true } : item))
      );
      setRetryQuery(text);
    } finally {
      setStreaming(false);
      aborter.current = null;
    }
  }
  async function deleteConversation() {
    if (!conversationId) return;
    setConfirmDelete(false);
    try {
      await meridianRequest(`/api/meridian/chat/conversations/${conversationId}`, {
        method: "DELETE",
      });
      void mutateCache(
        (key) => typeof key === "string" && key.startsWith(meridianKeys.conversations)
      );
      router.replace("/new");
    } catch (reason) {
      setError(reason);
    }
  }
  const isNew = !conversationId;
  return (
    <section
      className={`flex min-h-full min-w-0 flex-1 flex-col ${isNew ? "justify-center px-4 pb-24" : "px-4 py-8 sm:px-8"}`}
    >
      <p aria-live="polite" className="sr-only">
        {streamAnnouncement}
      </p>
      {detail.isLoading ? (
        <LoadingState label="Loading conversation…" />
      ) : detail.error ? (
        <div>
          <ApiFeedback error={detail.error} onRetry={() => void detail.mutate()} />
          <Link className="mt-4 inline-block text-sm underline" href="/chat">
            Return to chats
          </Link>
        </div>
      ) : (
        <>
          <header className={isNew ? "mx-auto mb-8 max-w-2xl text-center" : "mb-5"}>
            <p className="text-sm font-medium text-primary">
              {isNew ? "Meridian" : "Conversation"}
            </p>
            <h1 className="mt-2 text-3xl font-semibold tracking-tight">
              {isNew
                ? "Every answer, precisely located."
                : (detail.data?.title ?? "Untitled conversation")}
            </h1>
            {isNew ? (
              <p className="mt-3 text-muted-foreground">
                Ask a question grounded in your documents.
              </p>
            ) : null}
          </header>
          {error ? (
            <div className="mx-auto mb-4 w-full max-w-3xl">
              <ApiFeedback
                error={error}
                onRetry={() => {
                  setError(null);
                  if (retryQuery) setQuery(retryQuery);
                }}
              />
            </div>
          ) : null}
          <ScopeControl
            collectionNames={collectionNames}
            collections={collections.data?.collections ?? []}
            scope={scope}
            setCollectionIds={setCollectionIds}
            compact={isNew}
          />
          <div className={`w-full ${isNew ? "mx-auto max-w-3xl" : "flex-1 space-y-4"}`}>
            {!hasLibrary && !messages.length ? (
              <EmptyState title="Upload a document to start">
                Grounded chat needs ready documents.{" "}
                <Link className="underline" href="/documents">
                  Open documents
                </Link>
              </EmptyState>
            ) : messages.length ? (
              <MessageList
                messages={messages}
                scopeEvents={detail.data?.scope_events ?? []}
                collectionNames={collectionNames}
              />
            ) : null}
          </div>
          <form
            className={`mt-6 flex w-full flex-wrap gap-2 ${isNew ? "mx-auto max-w-3xl" : ""}`}
            onSubmit={submit}
          >
            <textarea
              aria-label="Chat message"
              className="min-h-14 min-w-0 flex-1 rounded-xl border border-border bg-background p-4"
              disabled={streaming || !hasLibrary}
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={
                hasLibrary ? "Ask about your documents" : "Upload documents to enable chat"
              }
            />
            <button
              className="rounded-xl bg-primary px-4 py-2 text-primary-foreground disabled:opacity-50"
              disabled={streaming || !query.trim() || !hasLibrary}
              type="submit"
            >
              {streaming ? "Thinking…" : "Send"}
            </button>
            {streaming ? (
              <button
                className="rounded-xl border border-border px-3 py-2"
                onClick={() => aborter.current?.abort()}
                type="button"
              >
                Stop
              </button>
            ) : null}
          </form>
          {!isNew ? (
            <button
              className="mt-5 self-start text-sm text-muted-foreground underline"
              onClick={() => setConfirmDelete(true)}
              type="button"
            >
              Delete conversation
            </button>
          ) : null}
        </>
      )}
      <ConfirmDialog
        confirmLabel="Delete conversation"
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void deleteConversation()}
        open={confirmDelete}
        title="Delete conversation?"
      >
        This cannot be undone.
      </ConfirmDialog>
    </section>
  );
}

function ScopeControl({
  collections,
  collectionNames,
  scope,
  setCollectionIds,
  compact,
}: {
  collections: NonNullable<CollectionListResponse["collections"]>;
  collectionNames: Map<string, string>;
  scope: RetrievalScopeResponse;
  setCollectionIds: (ids: string[]) => void;
  compact: boolean;
}) {
  const selected = scope.collection_ids;
  return (
    <section
      className={`w-full ${compact ? "mx-auto mb-3 max-w-3xl" : "mb-5"} rounded border border-border p-3`}
    >
      <p className="text-sm font-medium">
        Retrieval scope: {scope.mode === "all" ? "All documents" : "Selected collections"}
      </p>
      <select
        aria-label="Add collection to chat scope"
        className="mt-2 rounded border border-border p-2 text-sm"
        value=""
        onChange={(event) => {
          const id = event.target.value;
          if (id && !selected.includes(id)) setCollectionIds([...selected, id]);
        }}
      >
        <option value="">Add collection…</option>
        {collections
          .filter((collection) => !selected.includes(collection.id))
          .map((collection) => (
            <option key={collection.id} value={collection.id}>
              {collection.name}
            </option>
          ))}
      </select>
      {selected.length ? (
        <div className="mt-2 flex flex-wrap gap-2">
          {selected.map((id) => (
            <button
              className="rounded-full bg-muted px-2 py-1 text-xs"
              key={id}
              onClick={() => setCollectionIds(selected.filter((item) => item !== id))}
              type="button"
            >
              {collectionNames.get(id) ?? "Unavailable collection"} ×
            </button>
          ))}
          <button className="text-xs underline" onClick={() => setCollectionIds([])} type="button">
            Clear to all documents
          </button>
        </div>
      ) : null}
    </section>
  );
}
function MessageList({
  messages,
  scopeEvents,
  collectionNames,
}: {
  messages: LiveMessage[];
  scopeEvents: ConversationScopeEventResponse[];
  collectionNames: Map<string, string>;
}) {
  let sequence = 0;
  return (
    <>
      {messages.map((message) => {
        if (message.role === "user") sequence += 1;
        const events =
          message.role === "user"
            ? scopeEvents.filter((event) => event.effective_from_sequence === sequence)
            : [];
        return (
          <div key={message.id}>
            {events.map((event) => (
              <p
                className="mb-2 rounded bg-muted p-2 text-xs text-muted-foreground"
                key={event.version}
              >
                Scope changed to{" "}
                {event.mode === "all"
                  ? "All documents"
                  : event.collection_ids
                      .map((id) => collectionNames.get(id) ?? "Unavailable collection")
                      .join(", ")}
              </p>
            ))}
            <article
              className={`rounded-lg p-4 ${message.role === "user" ? "bg-muted" : "border border-border bg-card"}`}
            >
              <p className="mb-2 text-xs font-medium uppercase text-muted-foreground">
                {message.role === "user" ? "You" : "Meridian"}
                {message.failed ? " · incomplete" : ""}
              </p>
              <p className="whitespace-pre-wrap">{message.content || "…"}</p>
              {message.role === "assistant" && message.sources ? (
                <Sources sources={message.sources} />
              ) : null}
            </article>
          </div>
        );
      })}
    </>
  );
}
function Sources({ sources }: { sources: SourceCitation[] }) {
  if (!sources.length)
    return (
      <p className="mt-3 text-sm text-muted-foreground">
        No supporting sources were found; this is a completed grounded response.
      </p>
    );
  return (
    <details className="mt-3">
      <summary className="cursor-pointer text-sm font-medium">Sources ({sources.length})</summary>
      <div className="mt-2 grid gap-2">
        {sources.map((source) => (
          <article
            className="break-words rounded border border-border p-2 text-sm"
            key={`${source.document_id}:${source.chunk_id}`}
          >
            <p className="font-medium">
              {source.filename}
              {source.page_number ? ` · page ${source.page_number}` : ""}
            </p>
            <p className="mt-1 text-muted-foreground">{source.excerpt}</p>
          </article>
        ))}
      </div>
    </details>
  );
}
