"use client";

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { useState, type ReactNode } from "react";
import { AuthProvider } from "@/providers/auth-provider";
import { WorkspaceHandoffProvider } from "@/providers/workspace-handoff-provider";
import { TooltipProvider } from "@/components/ui/tooltip";
import { Toaster } from "@/components/ui/sonner";
import { GlobalChatWidget } from "@/components/chat/global-chat-widget";

export function AppProviders({ children }: { children: ReactNode }) {
  const [client] = useState(
    () =>
      new QueryClient({
        defaultOptions: {
          queries: {
            staleTime: 30_000,
            refetchOnWindowFocus: false,
            retry: 1,
          },
        },
      })
  );

  return (
    <QueryClientProvider client={client}>
      <AuthProvider>
        <WorkspaceHandoffProvider>
          <TooltipProvider delay={200}>
            {children}
            <GlobalChatWidget />
            <Toaster position="top-right" richColors closeButton />
          </TooltipProvider>
        </WorkspaceHandoffProvider>
      </AuthProvider>
    </QueryClientProvider>
  );
}
