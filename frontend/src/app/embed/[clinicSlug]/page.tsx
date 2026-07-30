"use client";

import { use } from "react";
import { ChatWidget } from "@/features/chat";
import { WidgetProvider } from "@/providers/widget-provider";

/** Embeddable clinic chat for external clinic websites. */
export default function EmbedPage({
  params,
}: {
  params: Promise<{ clinicSlug: string }>;
}) {
  const { clinicSlug } = use(params);

  return (
    <WidgetProvider mode="clinic" clinicSlug={clinicSlug}>
      <div className="flex h-dvh w-full flex-col bg-[#f8f8fc]">
        <ChatWidget
          mode="embedded"
          assistantMode="clinic"
          clinicSlug={clinicSlug}
          useStaffApi={false}
          defaultOpen
          className="h-full min-h-0 w-full max-w-none rounded-none shadow-none"
        />
      </div>
    </WidgetProvider>
  );
}
