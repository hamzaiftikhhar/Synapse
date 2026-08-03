"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { DashboardTopbar } from "@/components/dashboard/topbar";
import { ViewingClinicBanner } from "@/components/dashboard/viewing-clinic-banner";
import { DashboardWidgetProvider } from "@/components/dashboard/widget-provider-bridge";
import { useAuth } from "@/providers/auth-provider";

function DashboardShell({ children }: { children: React.ReactNode }) {
  const { user, clinic, isLoading } = useAuth();
  const pathname = usePathname();
  const router = useRouter();

  useEffect(() => {
    if (isLoading || !user) return;
    const isSuper = user.role === "SUPER_ADMIN";
    const onPlatform = pathname.startsWith("/dashboard/platform");
    const onProfile = pathname.startsWith("/dashboard/profile");

    // Super Admin without a clinic → stay on platform portal
    if (isSuper && !clinic && !onPlatform && !onProfile) {
      router.replace("/dashboard/platform");
    }
  }, [user, clinic, isLoading, pathname, router]);

  return (
    <DashboardWidgetProvider>
      <div className="flex min-h-screen bg-muted/30">
        <div className="hidden lg:block">
          <div className="sticky top-0 h-screen">
            <DashboardSidebar />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <DashboardTopbar />
          <ViewingClinicBanner />
          <main className="flex-1 p-4 pb-24 lg:p-6 lg:pb-24">{children}</main>
        </div>
      </div>
    </DashboardWidgetProvider>
  );
}

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedRoute>
      <DashboardShell>{children}</DashboardShell>
    </ProtectedRoute>
  );
}
