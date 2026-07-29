"use client";

import type { ReactNode } from "react";

import { isMeridianApiError } from "@/lib/api/client";

export function LoadingState({ label = "Loading Meridian…" }: { label?: string }) {
  return (
    <div aria-busy="true" className="animate-pulse rounded-lg border border-border bg-card p-6 text-sm text-muted-foreground">
      {label}
    </div>
  );
}

export function EmptyState({
  title,
  children,
}: {
  title: string;
  children: ReactNode;
}) {
  return (
    <section className="rounded-lg border border-dashed border-border bg-card p-8 text-center">
      <h2 className="text-base font-semibold">{title}</h2>
      <div className="mt-2 text-sm text-muted-foreground">{children}</div>
    </section>
  );
}

export function ApiFeedback({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const apiError = isMeridianApiError(error) ? error : null;
  const message = apiError?.message ?? "Meridian could not complete that request.";
  const retry = apiError?.retryAfterSeconds;

  return (
    <div aria-live="polite" className="rounded-lg border border-border bg-card p-4 text-sm">
      <p className="font-medium">{message}</p>
      {retry ? <p className="mt-1 text-muted-foreground">Try again in about {retry} seconds.</p> : null}
      {onRetry ? (
        <button className="mt-3 rounded-md bg-primary px-3 py-2 text-primary-foreground" onClick={onRetry} type="button">
          Try again
        </button>
      ) : null}
    </div>
  );
}
