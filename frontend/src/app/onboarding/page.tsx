"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { OnboardingFlow } from "@/features/onboarding/onboarding-flow";
import { useAuth } from "@/providers/auth-provider";

function OnboardingGuard() {
  const { clinic, tenants, user, isLoading } = useAuth();
  const router = useRouter();

  useEffect(() => {
    if (isLoading) return;
    if (user?.role === "SUPER_ADMIN" && !clinic) {
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
  }, [clinic, tenants, user, isLoading, router]);

  if (isLoading || !clinic || clinic.status === "active") {
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
