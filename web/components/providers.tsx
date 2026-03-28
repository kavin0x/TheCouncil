"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { useState } from "react";
import { AuthProvider } from "@/lib/auth";
import {
  ToastClose,
  ToastDescription,
  ToastProvider,
  ToastTitle,
  ToastViewport,
} from "@/components/ui";

export function Providers({ children }: { children: React.ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: { staleTime: 30_000, retry: 1 },
        },
      })
  );

  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <ToastProvider swipeDirection="right">
          {children}
          <ToastViewport />
        </ToastProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}

// Re-export primitives so pages can import from one place
export { ToastClose, ToastDescription, ToastTitle };
