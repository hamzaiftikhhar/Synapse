"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from "react";
import { useRouter } from "next/navigation";
import { useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import { WorkspaceLoader } from "@/components/auth/workspace-loader";
import { useAuth } from "@/providers/auth-provider";
import { queryKeys } from "@/hooks/api";
import { analyticsService } from "@/services";
import {
  clearHandoffActive,
  consumeHandoffToast,
  markHandoffActive,
  peekHandoffActive,
  stashHandoffToast,
  type HandoffToast,
} from "@/lib/workspace-handoff";

type HandoffResult = {
  href?: string;
  successToast?: string;
};

type BeginHandoffArgs = {
  label: string;
  href: string;
  successToast?: string;
  /**
   * hard = full reload (login/logout). soft = keep SPA alive so the
   * dashboard shell + skeletons paint immediately after the API returns.
   */
  navigation?: "hard" | "soft";
  run: () => Promise<HandoffResult | void>;
};

type HandoffContextValue = {
  active: boolean;
  beginHandoff: (args: BeginHandoffArgs) => Promise<void>;
};

const HandoffContext = createContext<HandoffContextValue | null>(null);

function shouldPrefetchClinicOverview(href: string) {
  return href === "/dashboard" || href.startsWith("/dashboard?");
}

export function WorkspaceHandoffProvider({ children }: { children: ReactNode }) {
  const { isLoading, isAuthenticated } = useAuth();
  const router = useRouter();
  const qc = useQueryClient();

  const [destinationCover, setDestinationCover] = useState<{ label: string } | null>(
    () => {
      if (typeof window === "undefined") return null;
      const active = peekHandoffActive();
      return active ? { label: active.label } : null;
    }
  );

  const [sourceCover, setSourceCover] = useState<string | null>(null);
  const coverLabel = sourceCover ?? destinationCover?.label ?? null;

  const beginHandoff = useCallback(
    async ({
      label,
      href,
      successToast,
      navigation = "hard",
      run,
    }: BeginHandoffArgs) => {
      setSourceCover(label);
      if (navigation === "hard") {
        markHandoffActive(label);
      }
      try {
        const result = (await run()) ?? {};
        const dest = result.href ?? href;
        const message = result.successToast ?? successToast;

        if (navigation === "soft") {
          // Start clinic home data while the cover is still up, then reveal
          // the shell so skeletons (or warm cache) paint immediately.
          if (shouldPrefetchClinicOverview(dest)) {
            void qc.prefetchQuery({
              queryKey: queryKeys.analyticsOverview("30d"),
              queryFn: () => analyticsService.overview("30d"),
            });
          }
          setSourceCover(null);
          clearHandoffActive();

          const from = window.location.pathname;
          const crossingPlatform =
            from.startsWith("/dashboard/platform") !==
            dest.startsWith("/dashboard/platform");
          // Soft replace can race the dashboard layout remount when the
          // clinic key flips; platform ↔ clinic (and same-path remounts)
          // need a hard assign. Stash the toast so it survives the reload.
          if (crossingPlatform || from === dest) {
            if (message) {
              stashHandoffToast({ type: "success", message });
            }
            markHandoffActive(label);
            setSourceCover(label);
            window.location.assign(dest);
            return;
          }

          router.replace(dest);
          if (message) {
            window.requestAnimationFrame(() => toast.success(message));
          }
          return;
        }

        if (message) {
          stashHandoffToast({ type: "success", message });
        }
        window.location.assign(dest);
      } catch (err) {
        clearHandoffActive();
        setSourceCover(null);
        throw err;
      }
    },
    [qc, router]
  );

  // Hard-nav destination only: drop cover when auth boot finishes, then toast.
  useEffect(() => {
    if (isLoading) return;
    if (!destinationCover) return;

    const pending: HandoffToast | null = consumeHandoffToast();
    clearHandoffActive();
    setDestinationCover(null);

    if (!isAuthenticated || !pending) return;

    const outer = window.requestAnimationFrame(() => {
      window.requestAnimationFrame(() => {
        if (pending.type === "success") toast.success(pending.message);
        else toast.error(pending.message);
      });
    });
    return () => window.cancelAnimationFrame(outer);
  }, [isLoading, isAuthenticated, destinationCover]);

  const value = useMemo(
    () => ({ active: Boolean(coverLabel), beginHandoff }),
    [coverLabel, beginHandoff]
  );

  return (
    <HandoffContext.Provider value={value}>
      {children}
      {coverLabel ? (
        <div className="fixed inset-0 z-[200]" aria-live="polite" aria-busy="true">
          <WorkspaceLoader label={coverLabel} />
        </div>
      ) : null}
    </HandoffContext.Provider>
  );
}

export function useWorkspaceHandoff() {
  const ctx = useContext(HandoffContext);
  if (!ctx) {
    throw new Error("useWorkspaceHandoff must be used within WorkspaceHandoffProvider");
  }
  return ctx;
}

export function useWorkspaceHandoffOptional() {
  return useContext(HandoffContext);
}
