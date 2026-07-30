"use client";

import { ProtectedRoute } from "@/components/auth/protected-route";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { DashboardTopbar } from "@/components/dashboard/topbar";
import { DashboardWidgetProvider } from "@/components/dashboard/widget-provider-bridge";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <ProtectedRoute>
      <DashboardWidgetProvider>
        <div className="flex min-h-screen bg-muted/30">
        <div className="hidden lg:block">
          <div className="sticky top-0 h-screen">
            <DashboardSidebar />
          </div>
        </div>
        <div className="flex min-w-0 flex-1 flex-col">
          <DashboardTopbar />
          <main className="flex-1 p-4 pb-24 lg:p-6 lg:pb-24">{children}</main>
        </div>
        </div>
      </DashboardWidgetProvider>
    </ProtectedRoute>
  );
}
