"use client";

import type { ReactNode } from "react";

import { isMeridianApiError } from "@/lib/api/client";
import type { MeridianApiError } from "@/lib/api/contracts";

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
  const message = feedbackMessage(apiError, error);
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

function feedbackMessage(apiError: MeridianApiError | null, error: unknown): string {
  if (!apiError) return navigator.onLine === false ? "You appear to be offline. Reconnect and try again." : "Meridian could not complete that request.";
  if (apiError.status === 401) return "Your session has expired. Sign in again to continue.";
  if (apiError.status === 403) return "You do not have permission to perform this action.";
  if (apiError.status === 404) return "This item is no longer available.";
  if (apiError.status === 422) return apiError.message;
  if (apiError.status === 429 || apiError.status === 503) return apiError.message;
  return apiError.message || (error instanceof Error ? "Meridian could not complete that request." : "Meridian could not complete that request.");
}
