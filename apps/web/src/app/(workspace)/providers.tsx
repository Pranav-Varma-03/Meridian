"use client";

import { SWRConfig } from "swr";
import { ThemeProvider } from "@/components/theme-provider";

export function WorkspaceProviders({ children }: { children: React.ReactNode }) {
  return (
    <ThemeProvider><SWRConfig
      value={{
        revalidateOnFocus: true,
        shouldRetryOnError: false,
        dedupingInterval: 2_000,
      }}
    >{children}</SWRConfig></ThemeProvider>
  );
}
