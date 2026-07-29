import type {
  ApiErrorEnvelope,
  CollectionResponse,
  DocumentResponse,
} from "@meridian/shared";

export class MeridianApiError extends Error {
  readonly code: string;
  readonly requestId: string | null;
  readonly retryAfterSeconds: number | null;
  readonly status: number;

  constructor({
    code,
    message,
    requestId,
    retryAfterSeconds,
    status,
  }: {
    code: string;
    message: string;
    requestId: string | null;
    retryAfterSeconds: number | null;
    status: number;
  }) {
    super(message);
    this.name = "MeridianApiError";
    this.code = code;
    this.requestId = requestId;
    this.retryAfterSeconds = retryAfterSeconds;
    this.status = status;
  }
}

function isApiErrorEnvelope(value: unknown): value is ApiErrorEnvelope {
  if (!value || typeof value !== "object" || !("error" in value)) {
    return false;
  }

  const error = (value as { error?: unknown }).error;
  return Boolean(
    error &&
      typeof error === "object" &&
      typeof (error as { code?: unknown }).code === "string" &&
      typeof (error as { message?: unknown }).message === "string",
  );
}

function retryAfterSeconds(value: string | null): number | null {
  if (!value) {
    return null;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) && parsed > 0 ? Math.ceil(parsed) : null;
}

export async function apiErrorFromResponse(response: Response): Promise<MeridianApiError> {
  let payload: unknown = null;
  try {
    payload = await response.clone().json();
  } catch {
    // Only the documented envelope is allowed to influence a user-visible message.
  }

  const envelope = isApiErrorEnvelope(payload) ? payload.error : null;
  return new MeridianApiError({
    code: envelope?.code ?? "API_REQUEST_FAILED",
    message: envelope?.message ?? "Meridian could not complete that request.",
    requestId: envelope?.request_id ?? response.headers.get("X-Request-ID"),
    retryAfterSeconds: retryAfterSeconds(response.headers.get("Retry-After")),
    status: response.status,
  });
}

export interface DocumentViewModel {
  id: string;
  filename: string;
  status: DocumentResponse["status"];
  collectionId: string | null;
  createdAt: Date;
  chunkCount: number | null;
  fileSize: number;
}

export function toDocumentViewModel(document: DocumentResponse): DocumentViewModel {
  return {
    id: document.id,
    filename: document.filename,
    status: document.status,
    collectionId: document.collection_id,
    createdAt: new Date(document.created_at),
    chunkCount: document.chunk_count,
    fileSize: document.file_size,
  };
}

export interface CollectionViewModel {
  id: string;
  name: string;
  description: string | null;
  documentCount: number;
  createdAt: Date;
}

export function toCollectionViewModel(
  collection: CollectionResponse,
): CollectionViewModel {
  return {
    id: collection.id,
    name: collection.name,
    description: collection.description,
    documentCount: collection.document_count,
    createdAt: new Date(collection.created_at),
  };
}
