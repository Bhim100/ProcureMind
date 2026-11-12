"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AuditorProvider } from "@/lib/auditor-session";
import { DemoFilterProvider } from "@/lib/demo-filter-context";

export function Providers({ children }: { children: ReactNode }) {
  const [queryClient] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 5 * 1000,
            retry: 1,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={queryClient}>
      <AuditorProvider>
        <DemoFilterProvider>{children}</DemoFilterProvider>
      </AuditorProvider>
    </QueryClientProvider>
  );
}

