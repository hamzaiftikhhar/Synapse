"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { OnboardingFlow } from "@/features/onboarding/onboarding-flow";
import { useAuth } from "@/providers/auth-provider";

function OnboardingGuard() {
  const { clinic, tenants, user, isLoading, canExitClinic } = useAuth();
  const router = useRouter();
  const isSuper = user?.role === "SUPER_ADMIN";
  const impersonating = isSuper && Boolean(clinic) && canExitClinic;

  useEffect(() => {
    if (isLoading) return;
    if (isSuper && !impersonating) {
      // Platform mode — Super Admin is not attached to a clinic.
      router.replace("/dashboard/platform");
      return;
    }
    if (clinic?.status === "active") {
      router.replace("/dashboard");
      return;
    }
    if (!clinic && (tenants?.length ?? 0) === 0) {
      router.replace("/onboarding/create-clinic");
    }
  }, [clinic, tenants, isSuper, impersonating, isLoading, router]);

  if (
    isLoading ||
    !clinic ||
    clinic.status === "active" ||
    (isSuper && !impersonating)
  ) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-background">
        <div className="size-8 animate-spin rounded-full border-2 border-primary border-t-transparent" />
      </div>
    );
  }

  return <OnboardingFlow />;
}

export default function OnboardingPage() {
  return (
    <ProtectedRoute>
      <OnboardingGuard />
    </ProtectedRoute>
  );
}
