"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth-provider";

export function useRequireSuperAdmin() {
  const { user, isLoading } = useAuth();
  const router = useRouter();
  const allowed = user?.role === "SUPER_ADMIN";

  useEffect(() => {
    if (!isLoading && user && !allowed) {
      router.replace("/dashboard");
    }
  }, [allowed, isLoading, router, user]);

  return { allowed, ready: !isLoading && allowed };
}
