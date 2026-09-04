"use client";

import { useEffect } from "react";
import { usePathname, useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { DashboardThemeProvider } from "@/components/dashboard/theme-provider";
import { DashboardTopbar } from "@/components/dashboard/topbar";
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
      return;
    }

    // Entered into a clinic → leave platform chrome for the clinic workspace.
    // Staying on /dashboard/platform/* while clinic is set left the
    // workspace switcher showing the clinic but the sidebar still on
    // super-admin nav (Enter looked like a no-op).
    if (isSuper && clinic && onPlatform) {
      router.replace(clinic.status === "onboarding" ? "/onboarding" : "/dashboard");
      return;
    }

    // Clinic staff must pick a tenant before any /dashboard route — login
    // without clinic_slug issues a JWT with no clinic, so landing here
    // via ?next=/dashboard would 400 every tenant-scoped API.
    if (!isSuper && !clinic && !onProfile) {
      router.replace("/select-tenant");
      return;
    }

    // Unfinished clinic setup → resume onboarding.
    if (clinic && clinic.status !== "active" && !onProfile) {
      router.replace("/onboarding");
    }
  }, [user, clinic, isLoading, pathname, router]);

  // Remount the whole clinic chrome when the active tenant changes. Soft
  // navigations to the same `/dashboard` route are a no-op in the App Router,
  // so without this key the previous clinic's pages keep their local state
  // (and any residual query observers) until the user clicks elsewhere.
  const workspaceKey = clinic?.slug ?? (user?.role === "SUPER_ADMIN" ? "platform" : "none");

  return (
    <DashboardThemeProvider>
      <DashboardWidgetProvider>
        <div key={workspaceKey} className="flex min-h-screen">
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
    </DashboardThemeProvider>
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
