export default function Home() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center p-24">
      <div className="text-center">
        <h1 className="text-4xl font-bold tracking-tight mb-4">
          Meridian
        </h1>
        <p className="text-muted-foreground text-lg mb-8">
          Intelligent document search and chat
        </p>
        <a
          href="/dashboard"
          className="inline-flex items-center justify-center rounded-md bg-primary px-6 py-3 text-sm font-medium text-primary-foreground hover:opacity-90 transition-opacity"
        >
          Get Started
        </a>
      </div>
    </main>
  );
}
