import { EmptyState } from "@/components/app-feedback";

export default function CollectionsPage() {
  return (
    <section className="mx-auto min-h-screen max-w-6xl px-4 py-8 sm:px-8">
      <p className="text-sm font-medium text-primary">Library</p>
      <h1 className="mt-2 text-3xl font-semibold tracking-tight">Collections</h1>
      <p className="mt-3 max-w-2xl text-muted-foreground">
        Collections are an optional focus for retrieval; unfiled documents remain available in All documents scope.
      </p>
      <div className="mt-10"><EmptyState title="No collection view loaded">Collection management will appear here once the document-library feature is applied.</EmptyState></div>
    </section>
  );
}
