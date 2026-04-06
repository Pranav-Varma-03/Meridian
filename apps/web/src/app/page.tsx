import { auth0 } from "@/lib/auth0";

export default async function Home() {
  const session = await auth0.getSession();

  if (!session) {
    return (
      <main className="flex min-h-screen flex-col items-center justify-center p-24">
        <div className="text-center">
          <h1 className="text-4xl font-bold tracking-tight mb-4">Meridian</h1>
          <p className="text-muted-foreground text-lg mb-8">
            Intelligent document search and chat
          </p>
          <div className="flex flex-col items-center gap-3">
            <a
              href="/auth/login?screen_hint=signup"
              className="inline-flex items-center justify-center rounded-md bg-primary px-6 py-3 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
            >
              Sign up
            </a>
            <a href="/auth/login" className="text-sm underline underline-offset-4">
              Log in
            </a>
          </div>
        </div>
      </main>
    );
  }

  const apiBaseUrl = process.env.API_BASE_URL ?? "http://localhost:8000";

  try {
    // Use ID token from the authenticated web session for provisioning.
    // This avoids audience mismatches from access-token configuration.
    const idToken = session.tokenSet?.idToken;

    let bearerToken = idToken;
    if (!bearerToken) {
      const accessTokenResult = await auth0.getAccessToken();
      bearerToken = accessTokenResult?.token;
    }

    if (bearerToken) {
      const response = await fetch(`${apiBaseUrl}/api/v1/users/me`, {
        method: "POST",
        headers: {
          Authorization: `Bearer ${bearerToken}`,
        },
        cache: "no-store",
      });

      if (!response.ok) {
        console.error("User provisioning failed", {
          status: response.status,
          statusText: response.statusText,
        });
      }
    }
  } catch (error) {
    console.error("Failed to sync authenticated user to API", error);
  }

  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-4">Meridian</h1>
        <p className="text-muted-foreground text-lg mb-8">
          Logged in as {session.user.email ?? session.user.name}
        </p>
        <div className="flex flex-col items-center gap-3">
          <a
            href="/dashboard"
            className="inline-flex items-center justify-center rounded-md bg-primary px-6 py-3 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
          >
            Open Dashboard
          </a>
          <a href="/auth/logout" className="text-sm underline underline-offset-4">
            Log out
          </a>
        </div>
      </div>
    </main>
  );
}
