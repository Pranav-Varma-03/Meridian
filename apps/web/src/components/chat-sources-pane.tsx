"use client";

import type { SourceCitation } from "@meridian/shared";
import { useEffect, useId, useRef, useState } from "react";

export function ChatSourcesPane({
  messageId,
  sources,
  onClose,
}: {
  messageId: string;
  sources: SourceCitation[];
  onClose: () => void;
}) {
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [narrow, setNarrow] = useState(false);
  const panel = useRef<HTMLElement>(null);
  const close = useRef<HTMLButtonElement>(null);
  const titleId = useId();

  useEffect(() => {
    if (typeof window.matchMedia !== "function") return;
    const media = window.matchMedia("(max-width: 767px)");
    const update = () => setNarrow(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  useEffect(() => {
    setExpanded(new Set());
  }, [messageId]);

  useEffect(() => {
    if (narrow) close.current?.focus();
  }, [narrow]);

  function toggleSource(id: string) {
    setExpanded((current) => {
      const next = new Set(current);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function handleKeyDown(event: React.KeyboardEvent<HTMLElement>) {
    if (event.key === "Escape") {
      event.preventDefault();
      onClose();
      return;
    }
    if (!narrow || event.key !== "Tab") return;

    const focusable = panel.current?.querySelectorAll<HTMLElement>(
      'button:not([disabled]), [href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])'
    );
    if (!focusable?.length) return;
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

  const content = (
    <>
      <header className="flex items-start justify-between gap-4 border-b border-border px-4 py-4">
        <div className="min-w-0">
          <h2 className="text-base font-semibold" id={titleId}>Sources ({sources.length})</h2>
          <p className="mt-1 text-xs text-muted-foreground">Evidence used for this response</p>
        </div>
        <button
          aria-label="Close sources"
          className="grid h-8 w-8 shrink-0 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary"
          onClick={onClose}
          ref={close}
          type="button"
        >
          <CloseIcon />
        </button>
      </header>
      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {sources.length ? (
          <ol className="grid gap-2" aria-label="Sources for this response">
            {sources.map((source, index) => {
              const sourceId = `${source.document_id}:${source.generation}:${source.chunk_id}`;
              const contentId = `source-content-${sourceId}`;
              const isExpanded = expanded.has(sourceId);
              return (
                <li className="rounded-lg border border-border bg-card" key={sourceId}>
                  <h3>
                    <button
                      aria-controls={contentId}
                      aria-expanded={isExpanded}
                      className="flex w-full items-start gap-3 rounded-lg p-3 text-left transition-colors hover:bg-muted/60 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-primary"
                      onClick={() => toggleSource(sourceId)}
                      type="button"
                    >
                      <span className="mt-0.5 grid h-5 w-5 shrink-0 place-items-center rounded-full bg-muted text-[11px] font-semibold text-muted-foreground">
                        {index + 1}
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block break-words text-sm font-medium text-foreground">{source.filename}</span>
                      {source.page_number || source.section_heading ? (
                        <span className="mt-1 block text-xs text-muted-foreground">
                          {source.page_number ? `Page ${source.page_number}` : ""}
                          {source.page_number && source.section_heading ? " · " : ""}
                          {source.section_heading ?? ""}
                        </span>
                      ) : null}
                      {source.available === false ? (
                        <span className="mt-1 block text-xs text-muted-foreground">No longer active</span>
                      ) : null}
                      </span>
                      <ChevronIcon expanded={isExpanded} />
                    </button>
                  </h3>
                  {isExpanded ? (
                    <div className="border-t border-border px-3 pb-3 pt-3" id={contentId}>
                      {source.available === false ? (
                        <p className="mb-3 rounded-md bg-muted px-2 py-1.5 text-xs text-muted-foreground">
                          This source is no longer in your active library. The excerpt below is the evidence snapshot used for this response.
                        </p>
                      ) : null}
                      <p className="whitespace-pre-wrap break-words text-sm leading-6 text-muted-foreground">{source.excerpt}</p>
                    </div>
                  ) : null}
                </li>
              );
            })}
          </ol>
        ) : (
          <p className="rounded-lg border border-dashed border-border p-4 text-sm text-muted-foreground">
            No supporting sources were returned for this response.
          </p>
        )}
      </div>
    </>
  );

  if (narrow) {
    return (
      <div className="fixed inset-0 z-40 md:hidden">
        <button aria-label="Close sources" className="absolute inset-0 bg-foreground/30" onClick={onClose} type="button" />
        <section
          aria-labelledby={titleId}
          aria-modal="true"
          className="absolute inset-y-0 right-0 flex w-[min(24rem,calc(100vw-1.5rem))] flex-col border-l border-border bg-background shadow-2xl"
          id="chat-sources-inspector"
          onKeyDown={handleKeyDown}
          ref={panel}
          role="dialog"
        >
          {content}
        </section>
      </div>
    );
  }

  return (
    <aside
      aria-labelledby={titleId}
      className="hidden h-full w-[min(24rem,35vw)] shrink-0 flex-col border-l border-border bg-background md:flex"
      id="chat-sources-inspector"
      onKeyDown={handleKeyDown}
      ref={panel}
      tabIndex={-1}
    >
      {content}
    </aside>
  );
}

function ChevronIcon({ expanded }: { expanded: boolean }) {
  return <svg aria-hidden="true" className={`mt-1 shrink-0 transition-transform ${expanded ? "rotate-180" : ""}`} fill="none" height="16" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.8" viewBox="0 0 24 24" width="16"><path d="m6 9 6 6 6-6" /></svg>;
}

function CloseIcon() {
  return <svg aria-hidden="true" fill="none" height="18" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" viewBox="0 0 24 24" width="18"><path d="m6 6 12 12M18 6 6 18" /></svg>;
}
