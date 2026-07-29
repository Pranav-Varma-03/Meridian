import { EmptyState } from "@/components/app-feedback";

export default function DocumentsPage() {
  return (
    <section className="mx-auto min-h-screen max-w-6xl px-4 py-8 sm:px-8">
      <p className="text-sm font-medium text-primary">Library</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Documents</h1>
      <p className="mt-3 max-w-2xl text-muted-foreground">
        Uploads, lifecycle status, deletion, and permitted re-ingestion are available in the document-library feature.
      </p>
      <div className="mt-10"><EmptyState title="No document view loaded">Document management will appear here once the library feature is applied.</EmptyState></div>
    </section>
  );
}
