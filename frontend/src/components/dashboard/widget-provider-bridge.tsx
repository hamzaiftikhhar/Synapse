"use client";

import { useAuth } from "@/providers/auth-provider";
import { getActiveTenant } from "@/lib/api/client";
import { WidgetProvider } from "@/providers/widget-provider";

/** Injects clinic tenant context for dashboard staff chat testing. */
export function DashboardWidgetProvider({
  children,
}: {
  children: React.ReactNode;
}) {
  const { clinic } = useAuth();
  // Super-admin "viewing as" uses X-Tenant-ID / active tenant even when
  // auth.clinic is still unset on some pages.
  const slug =
    clinic?.slug ??
    (typeof window !== "undefined" ? getActiveTenant() : null);

  return (
    <WidgetProvider mode="clinic" clinicSlug={slug}>
      {children}
    </WidgetProvider>
  );
}
