"use client";

const MAX_VISIBLE_PAGES = 7;

function visiblePages(currentPage: number, totalPages: number): number[] {
  if (totalPages <= MAX_VISIBLE_PAGES) {
    return Array.from({ length: totalPages }, (_, index) => index + 1);
  }

  const start = Math.max(1, Math.min(currentPage - 3, totalPages - MAX_VISIBLE_PAGES + 1));
  return Array.from({ length: MAX_VISIBLE_PAGES }, (_, index) => start + index);
}

export function Pagination({
  currentPage,
  onPageChange,
  pageSize = 10,
  pending = false,
  total,
}: {
  currentPage: number;
  onPageChange: (page: number) => void;
  pageSize?: number;
  total: number;
  pending?: boolean;
}) {
  const totalPages = Math.ceil(total / pageSize);
  if (totalPages <= 1) return null;

  return <nav aria-label="Pagination" className="mt-5 flex flex-wrap items-center gap-2">
    <button className="rounded border border-border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50" disabled={pending || currentPage === 1} onClick={() => onPageChange(currentPage - 1)} type="button">Previous</button>
    <div className="flex flex-wrap items-center gap-1" aria-label="Page numbers">
      {visiblePages(currentPage, totalPages).map((page) => <button aria-current={page === currentPage ? "page" : undefined} className={`min-w-9 rounded border px-3 py-1.5 text-sm ${page === currentPage ? "border-primary bg-primary text-primary-foreground" : "border-border"}`} disabled={pending} key={page} onClick={() => onPageChange(page)} type="button">{page}</button>)}
    </div>
    <button className="rounded border border-border px-3 py-1.5 text-sm disabled:cursor-not-allowed disabled:opacity-50" disabled={pending || currentPage === totalPages} onClick={() => onPageChange(currentPage + 1)} type="button">{pending ? "Loading…" : "Next"}</button>
  </nav>;
}
