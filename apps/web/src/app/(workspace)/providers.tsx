"use client";

import { SWRConfig } from "swr";

export function WorkspaceProviders({ children }: { children: React.ReactNode }) {
  return (
    <SWRConfig
      value={{
        revalidateOnFocus: true,
        shouldRetryOnError: false,
        dedupingInterval: 2_000,
      }}
    >
      {children}
    </SWRConfig>
  );
}
