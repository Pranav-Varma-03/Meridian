"use client";

import type {
  CollectionListResponse,
  DocumentListResponse,
  DocumentResponse,
  DocumentUploadAccepted,
  ReingestionReason,
} from "@meridian/shared";
import { useCallback, useEffect, useRef, useState } from "react";
import { useDropzone } from "react-dropzone";
import useSWR from "swr";

import { ApiFeedback, EmptyState, ListSkeleton, StatusRegion } from "@/components/app-feedback";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Pagination } from "@/components/pagination";
import { meridianKeys, meridianRequest } from "@/lib/api/client";
import {
  ACCEPTED_UPLOAD_TYPES,
  hasActiveIngestion,
  statusLabel,
  uploadValidationMessage,
} from "@/lib/document-library";

const MAX_POLL_ATTEMPTS = 30;
const POLL_INTERVAL_MS = 2_000;
const PAGE_SIZE = 10;
const reasons: { value: ReingestionReason; label: string }[] = [
  { value: "manual_repair", label: "Manual repair" },
  { value: "model_migration", label: "Model migration" },
  { value: "chunking_change", label: "Chunking change" },
];

export function DocumentLibrary({ canReingest }: { canReingest: boolean }) {
  const [collectionId, setCollectionId] = useState("");
  const [page, setPage] = useState(1);
  const [notice, setNotice] = useState<string | null>(null);
  const [actionError, setActionError] = useState<unknown>(null);
  const [pendingDelete, setPendingDelete] = useState<DocumentResponse | null>(null);
  const [uploading, setUploading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [reingestingDocumentId, setReingestingDocumentId] = useState<string | null>(null);
  const [pollCount, setPollCount] = useState(0);
  const documentsKey = `${meridianKeys.documents(collectionId || undefined)}${collectionId ? "&" : "?"}limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`;
  const documents = useSWR<DocumentListResponse>(documentsKey, meridianRequest, { keepPreviousData: true });
  const collections = useSWR<CollectionListResponse>(meridianKeys.collections, meridianRequest);
  const active = hasActiveIngestion(documents.data?.documents ?? []);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  const refreshDocuments = useCallback(
    () => Promise.all([documents.mutate(), collections.mutate()]),
    [collections, documents]
  );
  useEffect(() => {
    if (!active || pollCount >= MAX_POLL_ATTEMPTS) return;
    timer.current = setTimeout(() => {
      setPollCount((count) => count + 1);
      void refreshDocuments();
    }, POLL_INTERVAL_MS);
    return () => {
      if (timer.current) clearTimeout(timer.current);
    };
  }, [active, pollCount, refreshDocuments]);
  useEffect(() => {
    if (!active) setPollCount(0);
  }, [active]);

  const upload = useCallback(
    async (file: File) => {
      if (uploading) return;
      const validationError = uploadValidationMessage(file);
      if (validationError) {
        setActionError(new Error(validationError));
        return;
      }
      const data = new FormData();
      data.set("file", file);
      setActionError(null);
      setNotice(`Uploading ${file.name}…`);
      setUploading(true);
      try {
        const path = `/api/meridian/documents/upload${collectionId ? `?collection_id=${encodeURIComponent(collectionId)}` : ""}`;
        const response = await fetch(path, { method: "POST", body: data });
        if (!response.ok)
          throw await (await import("@/lib/api/contracts")).apiErrorFromResponse(response);
        const accepted = (await response.json()) as DocumentUploadAccepted;
        setNotice(
          accepted.deduplicated
            ? accepted.message
            : "Upload accepted. Processing continues in the background."
        );
        setPollCount(0);
        await documents.mutate();
      } catch (error) {
        setActionError(error);
        setNotice(null);
      } finally {
        setUploading(false);
      }
    },
    [collectionId, documents, uploading]
  );
  const onDrop = useCallback(
    (files: File[]) => {
      const first = files[0];
      if (first) void upload(first);
    },
    [upload]
  );
  const dropzone = useDropzone({
    onDrop,
    multiple: false,
    accept: ACCEPTED_UPLOAD_TYPES,
    disabled: uploading,
  });

  async function confirmDeleteDocument() {
    if (!pendingDelete || deleting) return;
    const document = pendingDelete;
    setActionError(null);
    setDeleting(true);
    try {
      await meridianRequest(`/api/meridian/documents/${document.id}`, { method: "DELETE" });
      setPendingDelete(null);
      setNotice("Document removed. Cleanup has been queued.");
      await documents.mutate();
    } catch (error) {
      setActionError(error);
    } finally {
      setDeleting(false);
    }
  }
  async function reingest(document: DocumentResponse, reason: ReingestionReason) {
    if (reingestingDocumentId) return;
    setActionError(null);
    setReingestingDocumentId(document.id);
    setNotice(`Queueing re-ingestion for ${document.filename}…`);
    try {
      await meridianRequest("/api/meridian/ingest", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ document_id: document.id, reason }),
      });
      setNotice(
        "Re-ingestion queued. The current ready generation remains available until the new generation succeeds."
      );
      setPollCount(0);
      await documents.mutate();
    } catch (error) {
      setActionError(error);
      setNotice(null);
    } finally {
      setReingestingDocumentId(null);
    }
  }

  return (
    <section className="mx-auto min-h-full max-w-6xl px-4 py-8 sm:px-8">
      <p className="text-sm font-medium text-primary">Library</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Documents</h1>
      <p className="mt-3 max-w-3xl text-muted-foreground">
        Manage uploaded knowledge. A deletion hides the document immediately; background cleanup
        removes its file and vectors safely.
      </p>
      <div className="mt-6 flex flex-wrap items-end gap-3">
        <label className="grid gap-1 text-sm font-medium">
          Collection
          <select
            className="rounded-md border border-border bg-card p-2"
            value={collectionId}
            onChange={(event) => {
              setCollectionId(event.target.value);
              setPage(1);
              setPollCount(0);
            }}
          >
            <option value="">All documents</option>
            {collections.data?.collections.map((collection) => (
              <option key={collection.id} value={collection.id}>
                {collection.name}
              </option>
            ))}
          </select>
        </label>
        <a className="rounded-md border border-border px-3 py-2 text-sm" href="/collections">
          Manage collections
        </a>
      </div>
      <div
        {...dropzone.getRootProps()}
        aria-disabled={uploading}
        className={`mt-6 rounded-lg border border-dashed border-primary/50 bg-card p-8 text-center ${uploading ? "cursor-wait opacity-70" : "cursor-pointer"}`}
      >
        <input {...dropzone.getInputProps()} />
        <p className="font-medium">
          {uploading ? "Uploading file…" : "Drop a PDF, DOCX, or TXT file here, or choose a file"}
        </p>
        <p className="mt-1 text-sm text-muted-foreground">
          Maximum size: 10 MiB.{" "}
          {collectionId ? "The selected collection will be assigned." : "It will be left unfiled."}
        </p>
      </div>
      {notice ? (
        <p role="status" className="mt-4 rounded-md bg-muted p-3 text-sm">
          {notice}
        </p>
      ) : null}
      <StatusRegion>
        {uploading
          ? "Uploading file"
          : reingestingDocumentId
            ? "Queueing document re-ingestion"
            : deleting
              ? "Deleting document"
              : ""}
      </StatusRegion>
      {actionError ? (
        <div className="mt-4">
          <ApiFeedback
            error={actionError}
            onRetry={() => {
              setActionError(null);
              void refreshDocuments();
            }}
          />
        </div>
      ) : null}
      <div className="mt-8">
        {documents.isLoading ? (
          <ListSkeleton label="Loading documents…" />
        ) : documents.error ? (
          <ApiFeedback error={documents.error} onRetry={() => void refreshDocuments()} />
        ) : (documents.data?.documents.length ?? 0) === 0 ? (
          <EmptyState title="No documents yet">
            Upload a supported file to start building your library.
          </EmptyState>
        ) : (
          <>
            <DocumentTable
              documents={documents.data?.documents ?? []}
              canReingest={canReingest}
              onDelete={setPendingDelete}
              onReingest={reingest}
              reingestingDocumentId={reingestingDocumentId}
            />
            <Pagination
              currentPage={page}
              onPageChange={setPage}
              pageSize={PAGE_SIZE}
              total={documents.data?.total ?? 0}
              pending={documents.isValidating}
            />
          </>
        )}
      </div>
      {active && pollCount >= MAX_POLL_ATTEMPTS ? (
        <p className="mt-3 text-sm text-muted-foreground">
          Processing is still running. Refresh this page to check again.
        </p>
      ) : null}
      <ConfirmDialog
        confirmLabel={deleting ? "Deleting…" : "Delete document"}
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmDeleteDocument()}
        open={Boolean(pendingDelete)}
        pending={deleting}
        title="Delete document?"
      >
        {pendingDelete
          ? `Remove ${pendingDelete.filename}? It disappears immediately; file and vector cleanup continue safely in the background.`
          : null}
      </ConfirmDialog>
    </section>
  );
}

function DocumentTable({
  documents,
  canReingest,
  onDelete,
  onReingest,
  reingestingDocumentId,
}: {
  documents: DocumentResponse[];
  canReingest: boolean;
  onDelete: (document: DocumentResponse) => void;
  onReingest: (document: DocumentResponse, reason: ReingestionReason) => void;
  reingestingDocumentId: string | null;
}) {
  return (
    <div className="overflow-x-auto rounded-lg border border-border">
      <table className="w-full text-left text-sm">
        <thead className="bg-muted text-muted-foreground">
          <tr>
            <th className="p-3">Document</th>
            <th className="p-3">Status</th>
            <th className="p-3">Chunks</th>
            <th className="p-3">Actions</th>
          </tr>
        </thead>
        <tbody>
          {documents.map((document) => (
            <tr className="border-t border-border" key={document.id}>
              <td className="p-3">
                <p className="font-medium">{document.filename}</p>
                <p className="text-xs text-muted-foreground">
                  {document.latest_job?.generation
                    ? `Generation ${document.latest_job.generation} · `
                    : ""}
                  {Math.ceil(document.file_size / 1024)} KiB
                </p>
              </td>
              <td className="p-3">
                <span className="rounded-full bg-muted px-2 py-1 text-xs font-medium">
                  {statusLabel(document)}
                </span>
                {document.latest_job?.error ? (
                  <p className="mt-1 max-w-xs text-xs text-red-700">{document.latest_job.error}</p>
                ) : null}
              </td>
              <td className="p-3">{document.chunk_count ?? "—"}</td>
              <td className="p-3">
                <div className="flex flex-wrap gap-2">
                  <button
                    className="rounded border border-border px-2 py-1"
                    onClick={() => onDelete(document)}
                    type="button"
                  >
                    Delete
                  </button>
                  {canReingest ? (
                    <select
                      aria-label={`Re-ingest ${document.filename}`}
                      className="rounded border border-border px-2 py-1"
                      defaultValue=""
                      disabled={reingestingDocumentId !== null}
                      onChange={(event) => {
                        const value = event.target.value as ReingestionReason;
                        if (value) {
                          onReingest(document, value);
                          event.currentTarget.value = "";
                        }
                      }}
                    >
                      <option value="">
                        {reingestingDocumentId === document.id ? "Queueing…" : "Re-ingest…"}
                      </option>
                      {reasons.map((reason) => (
                        <option key={reason.value} value={reason.value}>
                          {reason.label}
                        </option>
                      ))}
                    </select>
                  ) : null}
                </div>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
