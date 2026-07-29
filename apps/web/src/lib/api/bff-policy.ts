export type AllowedMethod = "GET" | "POST" | "PATCH" | "DELETE";

const FORWARDED_REQUEST_HEADERS = ["accept", "content-type", "x-request-id"];

function isUuid(value: string | undefined): boolean {
  return Boolean(
    value &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(
        value,
      ),
  );
}

/** Fixed Meridian BFF route table. It is deliberately not a generic proxy policy. */
export function allowedMethodsForPath(path: readonly string[]): readonly AllowedMethod[] {
  const [resource, second, third] = path;
  if (
    path.length > 3 ||
    path.some((segment) => !segment || segment === "." || segment === "..")
  ) {
    return [];
  }

  if (resource === "documents") {
    if (!second) return ["GET"];
    if (second === "upload") return ["POST"];
    if (isUuid(second)) return ["GET", "DELETE"];
  }
  if (resource === "collections") {
    if (!second) return ["GET", "POST"];
    if (isUuid(second)) return ["GET", "PATCH", "DELETE"];
  }
  if (resource === "ingest") {
    if (!second) return ["POST"];
    if (isUuid(second)) return ["GET"];
  }
  if (resource === "chat") {
    if (!second) return ["POST"];
    if (second !== "conversations") return [];
    if (!third) return ["GET"];
    return isUuid(third) ? ["GET", "DELETE"] : [];
  }
  if (resource === "users" && second === "me" && !third) return ["POST"];
  if (resource === "auth" && second === "token-claims" && !third) return ["GET"];
  return [];
}

export function isAllowedMeridianRequest(path: readonly string[], method: string): boolean {
  return allowedMethodsForPath(path).includes(method as AllowedMethod);
}

export function hasSameOrigin(origin: string | null, applicationOrigin: string): boolean {
  return origin === applicationOrigin;
}

export function forwardedRequestHeaders(input: Headers, token: string): Headers {
  const headers = new Headers();
  for (const name of FORWARDED_REQUEST_HEADERS) {
    const value = input.get(name);
    if (value) headers.set(name, value);
  }
  headers.set("Authorization", `Bearer ${token}`);
  return headers;
}
