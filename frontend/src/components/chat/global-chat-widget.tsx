"use client";

import { usePathname } from "next/navigation";
import { ChatWidget } from "@/features/chat/chat-widget";
import { useAuth } from "@/providers/auth-provider";
import { useWidget } from "@/providers/widget-provider";

/** Site-wide floating chatbot — routes by page context. */
export function GlobalChatWidget() {
  const pathname = usePathname();
  const { clinic, isAuthenticated } = useAuth();
  const { mode, clinicSlug, config } = useWidget();

  const isDashboard = pathname?.startsWith("/dashboard");
  const isEmbed = pathname?.startsWith("/embed/");

  if (isEmbed) return null;

  const assistantMode = isDashboard && isAuthenticated ? "staff" : mode;

  return (
    <ChatWidget
      mode="widget"
      assistantMode={assistantMode}
      useStaffApi={assistantMode === "staff"}
      clinicSlug={clinicSlug ?? undefined}
      clinicName={
        config?.clinic_name ?? clinic?.name ?? (mode === "marketing" ? "Synapse" : undefined)
      }
    />
  );
}
