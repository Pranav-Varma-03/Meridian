import { apiErrorFromResponse, MeridianApiError } from "@/lib/api/contracts";

export const meridianKeys = {
  collections: "/api/meridian/collections",
  documents: (collectionId?: string) =>
    collectionId
      ? `/api/meridian/documents?collection_id=${encodeURIComponent(collectionId)}`
      : "/api/meridian/documents",
  conversations: "/api/meridian/chat/conversations",
} as const;

export async function meridianRequest<T>(
  path: string,
  init: RequestInit = {},
): Promise<T> {
  const response = await fetch(path, {
    ...init,
    headers: {
      Accept: "application/json",
      ...init.headers,
    },
  });

  if (!response.ok) {
    throw await apiErrorFromResponse(response);
  }

  if (response.status === 204) {
    return undefined as T;
  }

  return (await response.json()) as T;
}

export function isMeridianApiError(error: unknown): error is MeridianApiError {
  return error instanceof MeridianApiError;
}
