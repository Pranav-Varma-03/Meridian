export function hasReingestionPermission(claims: Record<string, unknown> | null): boolean {
  return Boolean(
    claims &&
      Array.isArray(claims.permissions) &&
      claims.permissions.includes("documents:reingest"),
  );
}
