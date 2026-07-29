"use client";

import { usePathname } from "next/navigation";
import { ChatWidget } from "@/features/chat/chat-widget";
import { useAuth } from "@/providers/auth-provider";

/**
 * Site-wide floating chatbot (bottom-right).
 * - Marketing / auth: demo replies
 * - Dashboard (signed in): staff chat API
 */
export function GlobalChatWidget() {
  const pathname = usePathname();
  const { clinic, isAuthenticated } = useAuth();

  // Avoid mounting twice inside hero embedded preview only — floating is always OK
  const isDashboard = pathname?.startsWith("/dashboard");
  const useStaff = Boolean(isDashboard && isAuthenticated);

  return (
    <ChatWidget
      mode="widget"
      demoMode={!useStaff}
      useStaffApi={useStaff}
      clinicName={
        useStaff
          ? clinic?.name ?? undefined
          : isDashboard
            ? clinic?.name
            : "Demo Clinic"
      }
    />
  );
}
