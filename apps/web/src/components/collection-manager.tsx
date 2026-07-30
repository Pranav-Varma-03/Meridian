"use client";

import type { CollectionListResponse, CollectionResponse } from "@meridian/shared";
import { FormEvent, useState } from "react";
import useSWR from "swr";

import { ApiFeedback, EmptyState, LoadingState } from "@/components/app-feedback";
import { ConfirmDialog } from "@/components/confirm-dialog";
import { Pagination } from "@/components/pagination";
import { meridianKeys, meridianRequest } from "@/lib/api/client";

const PAGE_SIZE = 10;

export function CollectionManager() {
  const [page, setPage] = useState(1);
  const collections = useSWR<CollectionListResponse>(
    `${meridianKeys.collections}?limit=${PAGE_SIZE}&offset=${(page - 1) * PAGE_SIZE}`,
    meridianRequest
  );
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [error, setError] = useState<unknown>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingDelete, setPendingDelete] = useState<CollectionResponse | null>(null);
  const [pendingRename, setPendingRename] = useState<CollectionResponse | null>(null);
  const [renameName, setRenameName] = useState("");

  async function create(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setError(null);
    try {
      await meridianRequest<CollectionResponse>(meridianKeys.collections, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: name.trim(), description: description.trim() || null }),
      });
      setName("");
      setDescription("");
      setNotice("Collection created.");
      await collections.mutate();
    } catch (requestError) {
      setError(requestError);
    }
  }
  async function rename() {
    if (!pendingRename) return;
    const nextName = renameName.trim();
    if (!nextName) {
      setError(new Error("Collection name is required."));
      return;
    }
    try {
      await meridianRequest(`/api/meridian/collections/${pendingRename.id}`, {
        method: "PATCH",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: nextName }),
      });
      setPendingRename(null);
      setNotice("Collection updated.");
      await collections.mutate();
    } catch (requestError) {
      setError(requestError);
    }
  }
  async function confirmRemove() {
    if (!pendingDelete) return;
    const collection = pendingDelete;
    setPendingDelete(null);
    try {
      await meridianRequest(`/api/meridian/collections/${collection.id}`, { method: "DELETE" });
      setNotice("Collection deleted; its documents are now unfiled.");
      await collections.mutate();
    } catch (requestError) {
      setError(requestError);
    }
  }
  return (
    <section className="mx-auto min-h-full max-w-5xl px-4 py-8 sm:px-8">
      <p className="text-sm font-medium text-primary">Library</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Collections</h1>
      <p className="mt-3 max-w-2xl text-muted-foreground">
        Collections are optional retrieval groupings. Deleting one never deletes its documents; they
        become unfiled.
      </p>
      <form
        className="mt-6 grid gap-3 rounded-lg border border-border bg-card p-4 sm:grid-cols-[1fr_2fr_auto]"
        onSubmit={create}
      >
        <input
          aria-label="Collection name"
          className="rounded border border-border bg-background p-2"
          value={name}
          onChange={(event) => setName(event.target.value)}
          placeholder="Collection name"
          required
          maxLength={120}
        />
        <input
          aria-label="Collection description"
          className="rounded border border-border bg-background p-2"
          value={description}
          onChange={(event) => setDescription(event.target.value)}
          placeholder="Optional description"
        />
        <button className="rounded bg-primary px-3 py-2 text-primary-foreground" type="submit">
          Create
        </button>
      </form>
      {notice ? (
        <p role="status" className="mt-4 rounded bg-muted p-3 text-sm">
          {notice}
        </p>
      ) : null}
      {error ? (
        <div className="mt-4">
          <ApiFeedback
            error={error}
            onRetry={() => {
              setError(null);
              void collections.mutate();
            }}
          />
        </div>
      ) : null}
      <div className="mt-8">
        {collections.isLoading ? (
          <LoadingState label="Loading collections…" />
        ) : collections.error ? (
          <ApiFeedback error={collections.error} onRetry={() => void collections.mutate()} />
        ) : (collections.data?.collections.length ?? 0) === 0 ? (
          <EmptyState title="No collections yet">
            Create one to organize documents without excluding unfiled files from All documents
            retrieval.
          </EmptyState>
        ) : (
          <>
            <ul className="grid gap-3">
              {collections.data?.collections.map((collection) => (
                <li className="rounded-lg border border-border bg-card p-4" key={collection.id}>
                  <div className="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h2 className="font-semibold">{collection.name}</h2>
                      {collection.description ? (
                        <p className="mt-1 text-sm text-muted-foreground">
                          {collection.description}
                        </p>
                      ) : null}
                      <p className="mt-2 text-xs text-muted-foreground">
                        {collection.document_count} document
                        {collection.document_count === 1 ? "" : "s"}
                      </p>
                    </div>
                    <div className="flex gap-2">
                      <button
                        className="rounded border border-border px-2 py-1 text-sm"
                        type="button"
                        onClick={() => {
                          setRenameName(collection.name);
                          setPendingRename(collection);
                        }}
                      >
                        Rename
                      </button>
                      <button
                        className="rounded border border-border px-2 py-1 text-sm"
                        type="button"
                        onClick={() => setPendingDelete(collection)}
                      >
                        Delete
                      </button>
                    </div>
                  </div>
                </li>
              ))}
            </ul>
            <Pagination
              currentPage={page}
              onPageChange={setPage}
              pageSize={PAGE_SIZE}
              total={collections.data?.total ?? 0}
            />
          </>
        )}
      </div>
      <ConfirmDialog
        confirmLabel="Save name"
        onCancel={() => setPendingRename(null)}
        onConfirm={() => void rename()}
        open={Boolean(pendingRename)}
        title="Rename collection"
      >
        <label className="grid gap-1 text-sm font-medium">
          Collection name
          <input
            aria-label="New collection name"
            className="rounded border border-border bg-background p-2"
            value={renameName}
            onChange={(event) => setRenameName(event.target.value)}
            maxLength={120}
          />
        </label>
      </ConfirmDialog>
      <ConfirmDialog
        confirmLabel="Delete collection"
        onCancel={() => setPendingDelete(null)}
        onConfirm={() => void confirmRemove()}
        open={Boolean(pendingDelete)}
        title="Delete collection?"
      >
        {pendingDelete
          ? `Delete ${pendingDelete.name}? Its documents stay active and become unfiled.`
          : null}
      </ConfirmDialog>
    </section>
  );
}
