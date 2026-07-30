"use client";

import { useAuth } from "@/providers/auth-provider";
import { WidgetProvider } from "@/providers/widget-provider";

/** Injects clinic tenant context for dashboard staff chat testing. */
export function DashboardWidgetProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { clinic } = useAuth();
  return (
    <WidgetProvider mode="clinic" clinicSlug={clinic?.slug ?? null}>
      {children}
    </WidgetProvider>
  );
}
