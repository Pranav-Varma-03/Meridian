import type { DocumentResponse } from "@meridian/shared";

export const MAX_UPLOAD_BYTES = 10 * 1024 * 1024;
export const ACCEPTED_UPLOAD_TYPES = {
  "application/pdf": [".pdf"],
  "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "text/plain": [".txt"],
} as const;

const activeStatuses = new Set(["queued", "processing"]);

export function uploadValidationMessage(file: File): string | null {
  if (file.size > MAX_UPLOAD_BYTES) return "Files must be 10 MiB or smaller.";
  const extension = file.name.split(".").pop()?.toLowerCase();
  if (!extension || !["pdf", "docx", "txt"].includes(extension)) {
    return "Upload a PDF, DOCX, or TXT file.";
  }
  return null;
}

export function hasActiveIngestion(documents: readonly DocumentResponse[]): boolean {
  return documents.some((document) =>
    activeStatuses.has(document.latest_job?.status ?? document.status),
  );
}

export function statusLabel(document: DocumentResponse): string {
  const status = document.latest_job?.status ?? document.status;
  return status.charAt(0).toUpperCase() + status.slice(1);
}
