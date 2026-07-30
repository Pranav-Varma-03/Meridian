"use client";

import type { CollectionListResponse, ConversationMessage, ConversationResponse, ConversationScopeEventResponse, ConversationSummary, RetrievalScopeRequest, RetrievalScopeResponse, SourceCitation } from "@meridian/shared";
import { FormEvent, useEffect, useMemo, useRef, useState } from "react";
import useSWR from "swr";

import { ApiFeedback, EmptyState, LoadingState } from "@/components/app-feedback";
import { meridianKeys, meridianRequest } from "@/lib/api/client";
import { streamChat } from "@/lib/chat/client";

type LiveMessage = ConversationMessage & { provisional?: boolean; failed?: boolean; sources?: SourceCitation[] };
const PAGE_SIZE = 10;
const allScope: RetrievalScopeResponse = { mode: "all", collection_ids: [], version: 0 };

export function ChatWorkspace() {
  const [page, setPage] = useState(1); const [conversationId, setConversationId] = useState<string | null>(null);
  const [scope, setScope] = useState<RetrievalScopeResponse>(allScope); const [scopeDirty, setScopeDirty] = useState(false);
  const [messages, setMessages] = useState<LiveMessage[]>([]); const [query, setQuery] = useState(""); const [retryQuery, setRetryQuery] = useState<string | null>(null);
  const [streaming, setStreaming] = useState(false); const [error, setError] = useState<unknown>(null); const aborter = useRef<AbortController | null>(null);
  const conversations = useSWR<{ conversations: ConversationSummary[]; total: number }>(`${meridianKeys.conversations}?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`, meridianRequest);
  const detail = useSWR<ConversationResponse>(conversationId ? `/api/meridian/chat/conversations/${conversationId}` : null, meridianRequest);
  const collections = useSWR<CollectionListResponse>(`${meridianKeys.collections}?limit=100&offset=0`, meridianRequest);
  const hasLibrary = (collections.data?.collections.reduce((count, collection) => count + collection.document_count, 0) ?? 0) > 0;
  const collectionNames = useMemo(() => new Map((collections.data?.collections ?? []).map((item) => [item.id, item.name])), [collections.data]);

  useEffect(() => { if (!detail.data) return; setMessages(detail.data.messages); setScope(detail.data.retrieval_scope); setScopeDirty(false); }, [detail.data]);
  useEffect(() => () => aborter.current?.abort(), []);

  function newChat() { aborter.current?.abort(); setConversationId(null); setMessages([]); setScope(allScope); setScopeDirty(false); setError(null); setRetryQuery(null); }
  function selectConversation(id: string) { setConversationId(id); setError(null); setRetryQuery(null); }
  function preferredScope(): RetrievalScopeRequest { return scope.mode === "collections" ? { mode: "collections", collection_ids: scope.collection_ids } : { mode: "all" }; }
  function setCollectionIds(ids: string[]) { setScope({ mode: ids.length ? "collections" : "all", collection_ids: ids, version: scope.version }); setScopeDirty(true); }

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault(); const text = query.trim(); if (!text || streaming) return;
    if (!hasLibrary) { setError(new Error("Upload a document before starting a grounded conversation.")); return; }
    const temporaryAssistantId = `assistant-${crypto.randomUUID()}`; const temporaryUserId = `user-${crypto.randomUUID()}`;
    const user: LiveMessage = { id: temporaryUserId, role: "user", content: text, citations: {}, created_at: new Date().toISOString(), provisional: true };
    const assistant: LiveMessage = { id: temporaryAssistantId, role: "assistant", content: "", citations: {}, created_at: new Date().toISOString(), provisional: true };
    setMessages((current) => [...current, user, assistant]); setQuery(""); setRetryQuery(null); setError(null); setStreaming(true);
    const controller = new AbortController(); aborter.current = controller;
    const request: { query: string; conversation_id?: string; retrieval_scope?: RetrievalScopeRequest } = { query: text };
    if (conversationId) request.conversation_id = conversationId;
    if (!conversationId || scopeDirty) request.retrieval_scope = preferredScope();
    try {
      await streamChat(request, { signal: controller.signal, onEvent: (event) => {
        if (event.type === "text") setMessages((current) => current.map((message) => message.id === temporaryAssistantId ? { ...message, content: message.content + event.content } : message));
        if (event.type === "sources") setMessages((current) => current.map((message) => message.id === temporaryAssistantId ? { ...message, sources: event.content, citations: { sources: event.content } } : message));
        if (event.type === "error") { setError(new Error(event.message)); setMessages((current) => current.map((message) => message.id === temporaryAssistantId ? { ...message, failed: true } : message)); }
        if (event.type === "done") { setConversationId((current) => current ?? event.conversation_id); setScope((current) => event.retrieval_scope.version >= current.version ? event.retrieval_scope : current); setScopeDirty(false); setMessages((current) => current.map((message) => message.id === temporaryAssistantId || message.id === temporaryUserId ? { ...message, provisional: false } : message)); void conversations.mutate(); }
      }});
    } catch (reason) { if (!controller.signal.aborted) setError(reason); setMessages((current) => current.map((message) => message.id === temporaryAssistantId ? { ...message, failed: true } : message)); setRetryQuery(text); }
    finally { setStreaming(false); aborter.current = null; }
  }
  async function removeConversation(id: string) { if (!window.confirm("Delete this conversation? This cannot be undone.")) return; try { await meridianRequest(`/api/meridian/chat/conversations/${id}`, { method: "DELETE" }); if (conversationId === id) newChat(); await conversations.mutate(); } catch (reason) { setError(reason); } }

  return <section className="flex min-h-screen"><aside className="w-72 shrink-0 border-r border-border bg-card p-3"><button className="w-full rounded bg-primary px-3 py-2 text-sm text-primary-foreground" onClick={newChat} type="button">New chat</button><div className="mt-4">{conversations.isLoading ? <LoadingState label="Loading history…" /> : conversations.data?.conversations.map((item) => <div className="mt-1 flex gap-1" key={item.id}><button className={`min-w-0 flex-1 truncate rounded px-2 py-2 text-left text-sm ${conversationId === item.id ? "bg-muted" : "hover:bg-muted"}`} onClick={() => selectConversation(item.id)} type="button">{item.title ?? "Untitled conversation"}</button><button aria-label={`Delete ${item.title ?? "conversation"}`} className="px-2 text-sm" onClick={() => void removeConversation(item.id)} type="button">×</button></div>)}</div>{(conversations.data?.total ?? 0) > PAGE_SIZE ? <div className="mt-3 flex gap-2 text-sm"><button disabled={page === 1} onClick={() => setPage(page - 1)} type="button">Previous</button><span>Page {page}</span><button disabled={page * PAGE_SIZE >= (conversations.data?.total ?? 0)} onClick={() => setPage(page + 1)} type="button">Next</button></div> : null}</aside>
    <div className="flex min-w-0 flex-1 flex-col p-4 sm:p-8"><header><p className="text-sm font-medium text-primary">Workspace</p><h1 className="mt-1 text-2xl font-semibold">Chat with your documents</h1></header>{error ? <div className="mt-4"><ApiFeedback error={error} onRetry={() => { setError(null); if (retryQuery) setQuery(retryQuery); }} /></div> : null}
      <ScopeControl collectionNames={collectionNames} collections={collections.data?.collections ?? []} scope={scope} setCollectionIds={setCollectionIds} />
      <div className="mt-6 flex-1 space-y-4">{detail.isLoading ? <LoadingState label="Loading conversation…" /> : !hasLibrary && !messages.length ? <EmptyState title="Upload a document to start">Grounded chat needs ready documents. <a className="underline" href="/documents">Open documents</a></EmptyState> : messages.length === 0 ? <EmptyState title="Start a grounded conversation">Ask a question about your active documents.</EmptyState> : <MessageList messages={messages} scopeEvents={detail.data?.scope_events ?? []} collectionNames={collectionNames} />}</div>
      <form className="mt-6 flex gap-2" onSubmit={submit}><textarea aria-label="Chat message" className="min-h-12 flex-1 rounded border border-border bg-background p-3" disabled={streaming || !hasLibrary} value={query} onChange={(event) => setQuery(event.target.value)} placeholder={hasLibrary ? "Ask a question about your documents" : "Upload documents to enable chat"} /><button className="rounded bg-primary px-4 text-primary-foreground disabled:opacity-50" disabled={streaming || !query.trim() || !hasLibrary} type="submit">{streaming ? "Thinking…" : "Send"}</button>{streaming ? <button className="rounded border border-border px-3" onClick={() => aborter.current?.abort()} type="button">Stop</button> : null}</form>
    </div></section>;
}

function ScopeControl({ collections, collectionNames, scope, setCollectionIds }: { collections: NonNullable<CollectionListResponse["collections"]>; collectionNames: Map<string, string>; scope: RetrievalScopeResponse; setCollectionIds: (ids: string[]) => void }) { const selected = scope.collection_ids; return <section className="mt-5 rounded border border-border p-3"><p className="text-sm font-medium">Retrieval scope</p><p className="mt-1 text-sm text-muted-foreground">{scope.mode === "all" ? "All documents" : "Selected collections"}</p><select aria-label="Add collection to chat scope" className="mt-2 rounded border border-border p-2 text-sm" value="" onChange={(event) => { const id = event.target.value; if (id && !selected.includes(id)) setCollectionIds([...selected, id]); }}><option value="">Add collection…</option>{collections.filter((collection) => !selected.includes(collection.id)).map((collection) => <option key={collection.id} value={collection.id}>{collection.name}</option>)}</select>{selected.length ? <div className="mt-2 flex flex-wrap gap-2">{selected.map((id) => <button className="rounded-full bg-muted px-2 py-1 text-xs" key={id} onClick={() => setCollectionIds(selected.filter((item) => item !== id))} type="button">{collectionNames.get(id) ?? "Unavailable collection"} ×</button>)}<button className="text-xs underline" onClick={() => setCollectionIds([])} type="button">Clear to all documents</button></div> : null}</section>; }

function MessageList({ messages, scopeEvents, collectionNames }: { messages: LiveMessage[]; scopeEvents: ConversationScopeEventResponse[]; collectionNames: Map<string, string> }) { let userSequence = 0; return <>{messages.map((message) => { if (message.role === "user") userSequence += 1; const events = message.role === "user" ? scopeEvents.filter((event) => event.effective_from_sequence === userSequence) : []; return <div key={message.id}>{events.map((event) => <p className="mb-2 rounded bg-muted p-2 text-xs text-muted-foreground" key={event.version}>Scope changed to {event.mode === "all" ? "All documents" : event.collection_ids.map((id) => collectionNames.get(id) ?? "Unavailable collection").join(", ")}</p>)}<article className={`rounded-lg p-4 ${message.role === "user" ? "bg-muted" : "border border-border bg-card"}`}><p className="mb-2 text-xs font-medium uppercase text-muted-foreground">{message.role === "user" ? "You" : "Meridian"}{message.failed ? " · incomplete" : ""}</p><p className="whitespace-pre-wrap">{message.content || "…"}</p>{message.role === "assistant" && message.sources ? <Sources sources={message.sources} /> : null}</article></div>; })}</>; }

function Sources({ sources }: { sources: SourceCitation[] }) { if (!sources.length) return <p className="mt-3 text-sm text-muted-foreground">No supporting sources were found; this is a completed grounded response.</p>; return <details className="mt-3"><summary className="cursor-pointer text-sm font-medium">Sources ({sources.length})</summary><div className="mt-2 grid gap-2">{sources.map((source) => <article className="rounded border border-border p-2 text-sm" key={`${source.document_id}:${source.chunk_id}`}><p className="font-medium">{source.filename}{source.page_number ? ` · page ${source.page_number}` : ""}</p>{source.section_heading ? <p className="text-xs text-muted-foreground">{source.section_heading}</p> : null}<p className="mt-1 text-muted-foreground">{source.excerpt}</p><p className="mt-1 text-xs text-muted-foreground">Score: {source.score.toFixed(2)}</p></article>)}</div></details>; }
