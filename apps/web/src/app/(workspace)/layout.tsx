import { redirect } from "next/navigation";

import { WorkspaceShell } from "@/components/workspace-shell";
import { auth0 } from "@/lib/auth0";
import { getWorkspaceCapabilities } from "@/lib/server/capabilities";
import { provisionAuthenticatedUser } from "@/lib/server/meridian";
import { unauthenticatedWorkspaceRedirect } from "@/lib/server/workspace-session";

import { WorkspaceProviders } from "./providers";

export default async function AuthenticatedWorkspaceLayout({
  children,
}: Readonly<{ children: React.ReactNode }>) {
  const session = await auth0.getSession();
  if (!session) {
    redirect(unauthenticatedWorkspaceRedirect());
  }

  const [capabilities] = await Promise.all([
    getWorkspaceCapabilities(),
    provisionAuthenticatedUser(),
  ]);

  return (
    <WorkspaceProviders>
      <WorkspaceShell capabilities={capabilities} email={session.user.email}>
        {children}
      </WorkspaceShell>
    </WorkspaceProviders>
  );
}
