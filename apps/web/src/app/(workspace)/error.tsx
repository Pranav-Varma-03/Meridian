"use client";

import { ApiFeedback } from "@/components/app-feedback";

export default function WorkspaceError({ reset }: { reset: () => void }) {
  return <main className="mx-auto max-w-2xl p-8"><ApiFeedback error={new Error("Meridian workspace could not load.")} onRetry={reset} /></main>;
}
