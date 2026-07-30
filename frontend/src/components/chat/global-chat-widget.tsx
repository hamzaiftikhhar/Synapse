"use client";

import { usePathname } from "next/navigation";
import { ChatWidget } from "@/features/chat/chat-widget";
import { useAuth } from "@/providers/auth-provider";

/** Site-wide floating chatbot — all responses come from the backend API. */
export function GlobalChatWidget() {
  const pathname = usePathname();
  const { clinic, isAuthenticated } = useAuth();

  const isDashboard = pathname?.startsWith("/dashboard");
  const useStaff = Boolean(isDashboard && isAuthenticated);

  return (
    <ChatWidget
      mode="widget"
      useStaffApi={useStaff}
      clinicName={clinic?.name ?? undefined}
    />
  );
}
