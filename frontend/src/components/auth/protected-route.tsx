"use client";

import { useEffect, type ReactNode } from "react";
import { usePathname, useRouter } from "next/navigation";
import { useAuth } from "@/providers/auth-provider";
import { isExplicitLogout } from "@/lib/auth-redirect";
import { peekHandoffActive } from "@/lib/workspace-handoff";
import { WorkspaceLoader } from "@/components/auth/workspace-loader";
import { useWorkspaceHandoffOptional } from "@/providers/workspace-handoff-provider";

export function ProtectedRoute({ children }: { children: ReactNode }) {
  const { isAuthenticated, isLoading } = useAuth();
  const handoff = useWorkspaceHandoffOptional();
  const router = useRouter();
  const pathname = usePathname();

  useEffect(() => {
    if (!isLoading && !isAuthenticated) {
      // Hard handoff (logout / switch) owns navigation — don't soft-replace under it.
      if (handoff?.active || peekHandoffActive()) return;
      if (isExplicitLogout()) {
        router.replace("/login");
        return;
      }
      router.replace(`/login?next=${encodeURIComponent(pathname)}`);
    }
  }, [isAuthenticated, isLoading, pathname, router, handoff?.active]);

  if (isLoading || handoff?.active || peekHandoffActive()) {
    // Handoff provider already paints the cover — never stack a second loader.
    if (handoff?.active || peekHandoffActive()) {
      return null;
    }
    return <WorkspaceLoader label="Preparing your workspace" />;
  }

  if (!isAuthenticated) return null;
  return <>{children}</>;
}
