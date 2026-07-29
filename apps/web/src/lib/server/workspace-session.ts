import "server-only";

/**
 * Keep unauthenticated navigation intentional: the public landing page lets the
 * visitor choose Log in or Sign up instead of immediately starting Auth0 Universal
 * Login after a deep link to a workspace route.
 */
export function unauthenticatedWorkspaceRedirect(): string {
  return "/";
}
