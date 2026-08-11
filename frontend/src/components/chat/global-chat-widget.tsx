"use client";

import { useEffect, useState } from "react";
import { usePathname } from "next/navigation";
import { ChatWidget } from "@/features/chat/chat-widget";
import { getActiveTenant } from "@/lib/api/client";
import { useAuth } from "@/providers/auth-provider";
import { WidgetProvider } from "@/providers/widget-provider";

/**
 * Site-wide floating chatbot.
 *
 * Owns its own WidgetProvider so session_token from OTP verify persists for
 * appointment cancel/reschedule. (AppProviders renders this as a sibling of
 * page layouts, so it is outside dashboard/marketing WidgetProviders —
 * without a local provider, useWidget()'s setSessionToken is a no-op and
 * cancel posts session_token:"". )
 */
export function GlobalChatWidget() {
  const pathname = usePathname();
  const { clinic, isAuthenticated } = useAuth();
  // Re-read tenant when clinic context changes (super-admin "enter clinic").
  const [tenantSlug, setTenantSlug] = useState<string | null>(null);

  useEffect(() => {
    setTenantSlug(clinic?.slug ?? getActiveTenant());
  }, [clinic?.slug, pathname]);

  const isDashboard = pathname?.startsWith("/dashboard");
  const isEmbed = pathname?.startsWith("/embed/");

  if (isEmbed) return null;

  const assistantMode = isDashboard && isAuthenticated ? "staff" : "marketing";
  const clinicSlug =
    assistantMode === "staff"
      ? clinic?.slug ?? tenantSlug
      : null;

  return (
    <WidgetProvider
      mode={assistantMode === "staff" ? "clinic" : "marketing"}
      clinicSlug={clinicSlug}
    >
      <ChatWidget
        mode="widget"
        assistantMode={assistantMode}
        useStaffApi={assistantMode === "staff"}
        clinicSlug={clinicSlug ?? undefined}
        clinicName={
          clinic?.name ??
          (assistantMode === "marketing" ? "Synapse" : undefined)
        }
      />
    </WidgetProvider>
  );
}
