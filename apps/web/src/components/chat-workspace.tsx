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
import { FormEvent, useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import useSWR, { mutate as mutateCache } from "swr";

import { ApiFeedback, EmptyState, StatusRegion, TranscriptSkeleton } from "@/components/app-feedback";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { ChatSourcesPane } from "@/components/chat-sources-pane";
import { meridianKeys, meridianRequest } from "@/lib/api/client";
import { streamChat } from "@/lib/chat/client";

type LiveMessage = ConversationMessage & {
  provisional?: boolean;
  failed?: boolean;
  stopped?: boolean;
  sources?: SourceCitation[];
};
type SourceContext = {
  messageId: string;
  sources: SourceCitation[];
  trigger: HTMLButtonElement;
};
type ChatPhase = "idle" | "submitting" | "retrieving" | "streaming" | "complete" | "stopped" | "failed";
const allScope: RetrievalScopeResponse = { mode: "all", collection_ids: [], version: 0 };
const HISTORY_PAGE_SIZE = 50;

export function ChatWorkspace({ conversationId }: { conversationId?: string }) {
  const router = useRouter();
  const [scope, setScope] = useState<RetrievalScopeResponse>(allScope);
  const [scopeDirty, setScopeDirty] = useState(false);
  const [messages, setMessages] = useState<LiveMessage[]>([]);
  const [query, setQuery] = useState("");
  const [retryQuery, setRetryQuery] = useState<string | null>(null);
  const [phase, setPhase] = useState<ChatPhase>("idle");
  const [error, setError] = useState<unknown>(null);
  const phaseRef = useRef<ChatPhase>("idle");
  const isNew = !conversationId;
  const aborter = useRef<AbortController | null>(null);
  const activeQuery = useRef<string | null>(null);
  const transcript = useRef<HTMLDivElement | null>(null);
  const composer = useRef<HTMLTextAreaElement | null>(null);
  const [nearLatest, setNearLatest] = useState(true);
  const [loadingOlder, setLoadingOlder] = useState(false);
  const [historyPage, setHistoryPage] = useState({ hasMore: false, beforeSequence: null as number | null });
  const prependHeight = useRef<number | null>(null);
  const restoredPrependPosition = useRef(false);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [sourceContext, setSourceContext] = useState<SourceContext | null>(null);
  const [scopeOpen, setScopeOpen] = useState(false);
  const scopeTrigger = useRef<HTMLButtonElement>(null);
  const scopeOverlay = useRef<HTMLDivElement>(null);
  const detail = useSWR<ConversationResponse>(
    conversationId ? `/api/meridian/chat/conversations/${conversationId}?message_limit=${HISTORY_PAGE_SIZE}` : null,
    meridianRequest
  );
  const collections = useSWR<CollectionListResponse>(
    `${meridianKeys.collections}?limit=100&offset=0`,
    meridianRequest
  );
  const streaming = ["submitting", "retrieving", "streaming"].includes(phase);
  const scopeLoading = collections.isLoading;
  const scopeUnavailable = Boolean(collections.error);
  const scopeEditable = !scopeLoading && !scopeUnavailable && !streaming;
  const hasLibrary =
    (collections.data?.collections.reduce(
      (count, collection) => count + collection.document_count,
      0
    ) ?? 0) > 0;
  const collectionNames = useMemo(
    () => new Map((collections.data?.collections ?? []).map((item) => [item.id, item.name])),
    [collections.data]
  );

  function updatePhase(next: ChatPhase) {
    phaseRef.current = next;
    setPhase(next);
  }

  function closeSources() {
    const trigger = sourceContext?.trigger;
    setSourceContext(null);
    trigger?.focus();
  }

  function selectSources(messageId: string, sources: SourceCitation[], trigger: HTMLButtonElement) {
    if (sourceContext?.messageId === messageId) {
      closeSources();
      return;
    }
    setSourceContext({ messageId, sources, trigger });
  }

  useEffect(() => {
    if (detail.data) {
      setMessages(detail.data.messages);
      setScope(detail.data.retrieval_scope);
      setScopeDirty(false);
      setHistoryPage({ hasMore: detail.data.has_more_messages, beforeSequence: detail.data.next_before_sequence });
    }
  }, [detail.data]);
  useEffect(() => () => aborter.current?.abort(), []);
  useEffect(() => {
    if (!scopeOpen) return;
    const trigger = scopeTrigger.current;
    scopeOverlay.current?.focus();
    const closeForOutsidePointer = (event: PointerEvent) => {
      const target = event.target as Node;
      if (!scopeOverlay.current?.contains(target) && !scopeTrigger.current?.contains(target)) {
        setScopeOpen(false);
      }
    };
    window.addEventListener("pointerdown", closeForOutsidePointer);
    return () => {
      window.removeEventListener("pointerdown", closeForOutsidePointer);
      trigger?.focus();
    };
  }, [scopeOpen]);
  useEffect(() => {
    if (!scopeEditable) setScopeOpen(false);
  }, [scopeEditable]);
  useEffect(() => {
    const element = transcript.current;
    if (!element || isNew) return;
    if (prependHeight.current !== null) return;
    if (restoredPrependPosition.current) {
      restoredPrependPosition.current = false;
      return;
    }
    if (nearLatest) element.scrollTop = element.scrollHeight;
  }, [isNew, messages, nearLatest]);
  useLayoutEffect(() => {
    const element = transcript.current;
    if (element && prependHeight.current !== null) {
      element.scrollTop += element.scrollHeight - prependHeight.current;
      prependHeight.current = null;
      restoredPrependPosition.current = true;
    }
  }, [messages]);
  useLayoutEffect(() => {
    const element = composer.current;
    if (!element) return;
    element.style.height = "auto";
    element.style.height = `${Math.min(element.scrollHeight, 112)}px`;
  }, [query]);
  async function loadOlderMessages() {
    if (!conversationId || !historyPage.beforeSequence || loadingOlder) return;
    const element = transcript.current;
    if (element) prependHeight.current = element.scrollHeight;
    setLoadingOlder(true);
    try {
      const page = await meridianRequest<ConversationResponse>(
        `/api/meridian/chat/conversations/${conversationId}?message_limit=${HISTORY_PAGE_SIZE}&before_sequence=${historyPage.beforeSequence}`
      );
      setMessages((current) => {
        const known = new Set(current.map((message) => message.id));
        return [...page.messages.filter((message) => !known.has(message.id)), ...current];
      });
      setHistoryPage({ hasMore: page.has_more_messages, beforeSequence: page.next_before_sequence });
    } catch (reason) {
      prependHeight.current = null;
      setError(reason);
    } finally {
      setLoadingOlder(false);
    }
  }
  function preferredScope(): RetrievalScopeRequest {
    return scope.mode === "collections"
      ? { mode: "collections", collection_ids: scope.collection_ids }
      : { mode: "all" };
  }
  function setCollectionIds(ids: string[]) {
    if (!scopeEditable) return;
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
    if (!text || streaming || scopeLoading || scopeUnavailable) return;
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
    activeQuery.current = text;
    setError(null);
    updatePhase("submitting");
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
      updatePhase("retrieving");
      await streamChat(request, {
        signal: controller.signal,
        onEvent: (event) => {
          if (event.type === "text") {
            updatePhase("streaming");
            setMessages((current) =>
              current.map((item) =>
                item.id === assistantId ? { ...item, content: item.content + event.content } : item
              )
            );
          }
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
            updatePhase("failed");
            setRetryQuery(text);
            setMessages((current) =>
              current.map((item) =>
                item.id === assistantId
                  ? { ...item, failed: true, provisional: false }
                  : item.id === userId
                    ? { ...item, provisional: false }
                    : item
              )
            );
            controller.abort();
          }
          if (event.type === "done") {
            if (phaseRef.current === "stopped" || phaseRef.current === "failed") return;
            setScope((current) =>
              event.retrieval_scope.version >= current.version ? event.retrieval_scope : current
            );
            setScopeDirty(false);
            updatePhase("complete");
            activeQuery.current = null;
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
        updatePhase("failed");
      } else if (phaseRef.current !== "complete") {
        updatePhase("stopped");
      }
      setMessages((current) =>
        current.map((item) =>
          item.id === assistantId
            ? { ...item, failed: true, provisional: false }
            : item.id === userId
              ? { ...item, provisional: false }
              : item
        )
      );
      setRetryQuery(text);
    } finally {
      aborter.current = null;
    }
  }
  function stopStream() {
    if (!streaming) return;
    updatePhase("stopped");
    setRetryQuery(activeQuery.current);
    setMessages((current) =>
      current.map((message) =>
        message.role === "assistant" && message.provisional
          ? { ...message, stopped: true, provisional: false }
          : message.role === "user" && message.provisional
            ? { ...message, provisional: false }
            : message
      )
    );
    aborter.current?.abort();
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
  return (
    <div className="flex h-full min-h-0 min-w-0">
    <section
      className={`flex min-w-0 flex-1 flex-col ${isNew ? "min-h-full justify-center px-4 pb-24" : "h-full min-h-0 overflow-hidden px-4 py-8 sm:px-8"}`}
    >
      <StatusRegion>{phaseAnnouncement(phase)}</StatusRegion>
      {detail.isLoading ? (
        <div className="flex min-h-0 flex-1 flex-col">
          <div className="min-h-0 flex-1 overflow-y-auto pr-1"><TranscriptSkeleton /></div>
          <form className="mt-4 shrink-0 flex w-full items-end gap-2" onSubmit={(event) => event.preventDefault()}>
            <div className="flex min-w-0 flex-1 items-end rounded-2xl border border-border bg-card p-1.5 shadow-sm">
              <textarea aria-label="Chat message" className="min-h-10 min-w-0 flex-1 resize-y bg-transparent px-3 py-2 outline-none" disabled placeholder="Loading conversation…" />
              <button aria-label="Send message" className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground disabled:opacity-50" disabled type="submit"><ArrowUpIcon /></button>
            </div>
          </form>
        </div>
      ) : detail.error ? (
        <div>
          <ApiFeedback error={detail.error} onRetry={() => void detail.mutate()} />
          <Link className="mt-4 inline-block text-sm underline" href="/chat">
            Return to chats
          </Link>
        </div>
      ) : (
        <>
          {isNew ? (
            <header className="mx-auto mb-8 max-w-2xl text-center">
              <p className="text-sm font-medium text-primary">Meridian</p>
              <h1 className="mt-2 text-3xl font-semibold tracking-tight">Every answer, precisely located.</h1>
              <p className="mt-3 text-muted-foreground">Ask a question grounded in your documents.</p>
            </header>
          ) : null}
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
          {retryQuery && (phase === "failed" || phase === "stopped") ? (
            <button
              className="mx-auto mb-4 w-full max-w-3xl rounded border border-border px-3 py-2 text-sm"
              onClick={() => setQuery(retryQuery)}
              type="button"
            >
              Retry last question
            </button>
          ) : null}
          <div
            className={`relative w-full ${isNew ? "mx-auto max-w-3xl" : "min-h-0 flex-1"}`}
          >
            <div
              className={isNew ? "" : "h-full min-h-0 space-y-4 overflow-y-auto pr-1"}
              aria-busy={streaming || undefined}
              data-testid={isNew ? undefined : "conversation-transcript"}
              onScroll={(event) => {
                const element = event.currentTarget;
                setNearLatest(element.scrollHeight - element.scrollTop - element.clientHeight < 80);
              }}
              ref={isNew ? undefined : transcript}
            >
              {!isNew && historyPage.hasMore ? (
                <button
                  className="mb-3 rounded border border-border px-3 py-1 text-sm disabled:opacity-50"
                  disabled={loadingOlder}
                  onClick={() => void loadOlderMessages()}
                  type="button"
                >
                  {loadingOlder ? "Loading older messages…" : "Load older messages"}
                </button>
              ) : null}
              {!scopeLoading && !scopeUnavailable && !hasLibrary && !messages.length ? (
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
                  onSelectSources={selectSources}
                  sourceMessageId={sourceContext?.messageId ?? null}
                />
              ) : null}
            </div>
            {!isNew && !nearLatest ? (
              <button
                aria-label="Jump to latest"
                className="absolute bottom-4 right-4 z-10 grid h-11 w-11 place-items-center rounded-full border border-border bg-card text-foreground shadow-lg transition-all hover:-translate-y-0.5 hover:bg-muted hover:shadow-xl focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 active:translate-y-0"
                onClick={() => {
                  const element = transcript.current;
                  if (element) {
                    element.scrollTop = element.scrollHeight;
                    setNearLatest(true);
                  }
                }}
                title="Jump to latest"
                type="button"
              >
                <ArrowDownIcon />
              </button>
            ) : null}
          </div>
          <form
            className={`relative mt-4 shrink-0 flex w-full items-end gap-2 ${isNew ? "mx-auto max-w-3xl" : ""}`}
            onSubmit={submit}
          >
            <div className="flex min-w-0 flex-1 items-end rounded-2xl border border-border bg-card p-1.5 shadow-sm focus-within:border-primary">
              <textarea
                aria-label="Chat message"
                className="min-h-10 max-h-28 min-w-0 flex-1 resize-none overflow-y-auto bg-transparent px-3 py-2 outline-none"
                disabled={streaming || scopeLoading || scopeUnavailable || !hasLibrary}
                ref={composer}
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder={
                  scopeLoading
                    ? "Loading available collections…"
                    : scopeUnavailable
                      ? "Collection choices are unavailable"
                      : hasLibrary
                        ? "Ask about your documents"
                        : "Upload documents to enable chat"
                }
              />
              <button
                aria-label="Send message"
                aria-busy={streaming || undefined}
                className="grid h-10 w-10 shrink-0 place-items-center rounded-full bg-primary text-primary-foreground disabled:cursor-not-allowed disabled:opacity-50"
                disabled={streaming || scopeLoading || scopeUnavailable || !query.trim() || !hasLibrary}
                title={streaming ? (phase === "streaming" ? "Generating response" : "Searching documents") : "Send message"}
                type="submit"
              >
                <ArrowUpIcon />
              </button>
            </div>
            <div className="relative shrink-0">
              <button
                aria-controls="retrieval-scope-panel"
                aria-expanded={scopeOpen}
                aria-label={scopeTriggerLabel(scope, scopeLoading, scopeUnavailable)}
                className="relative grid h-11 w-11 place-items-center rounded-full border border-border bg-card shadow-sm transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary focus-visible:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
                disabled={!scopeEditable}
                onClick={() => setScopeOpen((open) => !open)}
                ref={scopeTrigger}
                title={scopeLoading ? "Loading retrieval scope" : scopeUnavailable ? "Retrieval scope unavailable" : "Manage retrieval scope"}
                type="button"
              >
                <ScopeIcon />
                {scope.mode === "collections" ? (
                  <span aria-hidden="true" className="absolute -right-1 -top-1 grid h-4 min-w-4 place-items-center rounded-full bg-primary px-1 text-[10px] font-semibold text-primary-foreground">
                    {scope.collection_ids.length}
                  </span>
                ) : null}
              </button>
              {scopeOpen ? (
                <ScopeOverlay
                  collectionNames={collectionNames}
                  collections={collections.data?.collections ?? []}
                  onClose={() => setScopeOpen(false)}
                  scope={scope}
                  setCollectionIds={setCollectionIds}
                  overlayRef={scopeOverlay}
                />
              ) : null}
            </div>
            {streaming ? (
              <button
                className="h-11 shrink-0 rounded-full border border-border px-4 text-sm"
                onClick={stopStream}
                type="button"
              >
                Stop
              </button>
            ) : null}
          </form>
          {!isNew ? <button className="mt-3 shrink-0 self-start text-xs text-muted-foreground underline" onClick={() => setConfirmDelete(true)} type="button">Delete conversation</button> : null}
        </>
      )}
    </section>
      {sourceContext ? (
        <ChatSourcesPane
          messageId={sourceContext.messageId}
          onClose={closeSources}
          sources={sourceContext.sources}
        />
      ) : null}
      <ConfirmDialog
        confirmLabel="Delete conversation"
        onCancel={() => setConfirmDelete(false)}
        onConfirm={() => void deleteConversation()}
        open={confirmDelete}
        title="Delete conversation?"
      >
        This cannot be undone.
      </ConfirmDialog>
    </div>
  );
}

function ScopeOverlay({
  collections,
  collectionNames,
  scope,
  setCollectionIds,
  onClose,
  overlayRef,
}: {
  collections: NonNullable<CollectionListResponse["collections"]>;
  collectionNames: Map<string, string>;
  scope: RetrievalScopeResponse;
  setCollectionIds: (ids: string[]) => void;
  onClose: () => void;
  overlayRef: React.RefObject<HTMLDivElement>;
}) {
  const selected = scope.collection_ids;
  return (
    <>
      <div aria-hidden="true" className="fixed inset-0 z-20 bg-foreground/10 sm:hidden" onClick={onClose} />
      <section
        aria-label="Retrieval scope"
        className="fixed inset-x-3 bottom-20 z-30 max-h-[min(28rem,calc(100dvh-6rem))] overflow-y-auto rounded-2xl border border-border bg-card p-4 shadow-xl sm:absolute sm:inset-auto sm:bottom-full sm:right-0 sm:mb-3 sm:w-96"
        id="retrieval-scope-panel"
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.preventDefault();
            onClose();
          }
        }}
        ref={overlayRef}
        role="dialog"
        tabIndex={-1}
      >
      <div className="flex items-start justify-between gap-4 border-b border-border pb-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold">Retrieval scope</h2>
          <p className="mt-1 text-xs text-muted-foreground">{scopeSummary(scope)} for your next answer</p>
        </div>
        <button aria-label="Close retrieval scope" className="rounded p-1 text-muted-foreground transition-colors hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary" onClick={onClose} type="button">×</button>
      </div>
      <select
        aria-label="Add collection to chat scope"
        className="mt-4 w-full rounded border border-border bg-background p-2 text-sm"
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
        <div className="mt-3 flex flex-wrap gap-2">
          {selected.map((id) => (
            <button
              className="rounded-full bg-muted px-2 py-1 text-xs hover:bg-muted/70"
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
      ) : <p className="mt-3 text-sm text-muted-foreground">All ready documents are included.</p>}
      </section>
    </>
  );
}

function scopeSummary(scope: RetrievalScopeResponse): string {
  return scope.mode === "all" ? "All documents" : `${scope.collection_ids.length} selected collection${scope.collection_ids.length === 1 ? "" : "s"}`;
}

function scopeTriggerLabel(
  scope: RetrievalScopeResponse,
  loading: boolean,
  unavailable: boolean
): string {
  if (loading) return "Retrieval scope: loading collection choices";
  if (unavailable) return "Retrieval scope unavailable";
  return `Manage retrieval scope: ${scopeSummary(scope)}`;
}

function ArrowUpIcon() {
  return <svg aria-hidden="true" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="18"><path d="M12 19V5M5 12l7-7 7 7" /></svg>;
}

function ArrowDownIcon() {
  return <svg aria-hidden="true" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" viewBox="0 0 24 24" width="18"><path d="M12 5v14m7-7-7 7-7-7" /></svg>;
}

function ScopeIcon() {
  return <svg aria-hidden="true" fill="none" height="19" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="19"><path d="M4 6h16M7 12h10M10 18h4" /><circle cx="8" cy="6" fill="currentColor" r="1.4" /><circle cx="15" cy="12" fill="currentColor" r="1.4" /><circle cx="11" cy="18" fill="currentColor" r="1.4" /></svg>;
}
function MessageList({
  messages,
  scopeEvents,
  collectionNames,
  onSelectSources,
  sourceMessageId,
}: {
  messages: LiveMessage[];
  scopeEvents: ConversationScopeEventResponse[];
  collectionNames: Map<string, string>;
  onSelectSources: (messageId: string, sources: SourceCitation[], trigger: HTMLButtonElement) => void;
  sourceMessageId: string | null;
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
                {message.stopped ? " · stopped" : ""}
              </p>
              {message.role === "assistant" && message.provisional && !message.content ? (
                <p aria-busy="true" className="text-muted-foreground">Searching your documents…</p>
              ) : message.role === "assistant" ? (
                <MarkdownAnswer content={message.content || "…"} />
              ) : (
                <p className="whitespace-pre-wrap">{message.content || "…"}</p>
              )}
              {message.role === "assistant" && !message.provisional ? (
                <ResponseActions
                  content={message.content}
                  messageId={message.id}
                  onSelectSources={onSelectSources}
                  sourcesOpen={sourceMessageId === message.id}
                  sources={message.sources ?? message.citations.sources ?? []}
                />
              ) : null}
            </article>
          </div>
        );
      })}
    </>
  );
}
function phaseAnnouncement(phase: ChatPhase): string {
  if (phase === "submitting") return "Sending your question.";
  if (phase === "retrieving") return "Searching your documents.";
  if (phase === "streaming") return "Meridian response is streaming.";
  if (phase === "complete") return "Meridian response complete.";
  if (phase === "stopped") return "Meridian response stopped. Your question is ready to retry.";
  if (phase === "failed") return "Meridian could not complete the response. Your question is ready to retry.";
  return "";
}

function MarkdownAnswer({ content }: { content: string }) {
  return (
    <div className="break-words text-sm leading-6 [&_a]:text-primary [&_a]:underline [&_a]:underline-offset-2 [&_blockquote]:my-3 [&_blockquote]:border-l-2 [&_blockquote]:border-primary/40 [&_blockquote]:pl-3 [&_code]:rounded [&_code]:bg-muted [&_code]:px-1 [&_code]:py-0.5 [&_code]:font-mono [&_h1]:mb-3 [&_h1]:text-xl [&_h1]:font-semibold [&_h2]:mb-2 [&_h2]:mt-5 [&_h2]:text-lg [&_h2]:font-semibold [&_h3]:mb-2 [&_h3]:mt-4 [&_h3]:font-medium [&_li]:my-1 [&_ol]:my-3 [&_ol]:list-decimal [&_ol]:pl-6 [&_p]:my-3 [&_p:first-child]:mt-0 [&_p:last-child]:mb-0 [&_pre]:my-3 [&_pre]:overflow-x-auto [&_pre]:rounded-lg [&_pre]:bg-muted [&_pre]:p-3 [&_pre_code]:bg-transparent [&_pre_code]:p-0 [&_table]:my-3 [&_table]:w-full [&_table]:border-collapse [&_td]:border [&_td]:border-border [&_td]:p-2 [&_th]:border [&_th]:border-border [&_th]:bg-muted [&_th]:p-2 [&_ul]:my-3 [&_ul]:list-disc [&_ul]:pl-6">
      <ReactMarkdown remarkPlugins={[remarkGfm]} skipHtml>
        {content}
      </ReactMarkdown>
    </div>
  );
}

function ResponseActions({
  content,
  messageId,
  onSelectSources,
  sourcesOpen,
  sources,
}: {
  content: string;
  messageId: string;
  onSelectSources: (messageId: string, sources: SourceCitation[], trigger: HTMLButtonElement) => void;
  sourcesOpen: boolean;
  sources: SourceCitation[];
}) {
  const [copied, setCopied] = useState(false);

  async function copyResponse() {
    try {
      await navigator.clipboard.writeText(content);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopied(false);
    }
  }

  return (
    <div className="mt-4 flex items-center gap-1 border-t border-border pt-2">
      <button
        aria-label="Copy response"
        className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        onClick={() => void copyResponse()}
        title="Copy response"
        type="button"
      >
        <CopyIcon />
        <span>{copied ? "Copied" : "Copy"}</span>
      </button>
      <button
        aria-controls="chat-sources-inspector"
        aria-expanded={sourcesOpen}
        aria-label="Sources"
        className="inline-flex h-8 items-center gap-1.5 rounded-md px-2 text-xs text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
        onClick={(event) => onSelectSources(messageId, sources, event.currentTarget)}
        title="View sources"
        type="button"
      >
        <SourcesIcon />
        <span>Sources</span>
        {sources.length ? <span className="text-muted-foreground">({sources.length})</span> : null}
      </button>
    </div>
  );
}

function CopyIcon() {
  return <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="15"><rect height="13" rx="2" width="13" x="8" y="8" /><path d="M16 8V5a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h3" /></svg>;
}

function SourcesIcon() {
  return <svg aria-hidden="true" fill="none" height="15" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="15"><path d="M4 6.5A2.5 2.5 0 0 1 6.5 4H11v15H6.5A2.5 2.5 0 0 0 4 21.5v-15ZM20 6.5A2.5 2.5 0 0 0 17.5 4H13v15h4.5a2.5 2.5 0 0 1 2.5 2.5v-15Z" /></svg>;
}
