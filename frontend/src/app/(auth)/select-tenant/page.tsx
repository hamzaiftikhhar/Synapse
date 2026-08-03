"use client";

import { Suspense, useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { ProtectedRoute } from "@/components/auth/protected-route";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { APP_NAME } from "@/constants";

function SelectTenantInner() {
  const { tenants, selectTenant, user, isLoading } = useAuth();
  const router = useRouter();
  const search = useSearchParams();
  const auto = search.get("auto");
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (isLoading || !auto) return;
    void (async () => {
      try {
        setBusy(auto);
        await selectTenant(auto);
        router.replace("/dashboard");
      } catch (err) {
        toast.error(getApiErrorMessage(err));
        setBusy(null);
      }
    })();
  }, [auto, isLoading, selectTenant, router]);

  async function choose(slug: string) {
    setBusy(slug);
    try {
      await selectTenant(slug);
      router.replace("/dashboard");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
      setBusy(null);
    }
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-muted/30 px-6">
      <div className="w-full max-w-md rounded-[6px] border border-border bg-white p-8 shadow-sm">
        <p className="text-lg font-semibold text-navy">{APP_NAME}</p>
        <h1 className="mt-4 text-xl font-semibold tracking-tight">
          Choose a clinic
        </h1>
        <p className="mt-1 text-sm text-muted-foreground">
          Signed in as {user?.email}
        </p>
        <div className="mt-6 space-y-2">
          {tenants.length === 0 ? (
            <div className="space-y-3">
              <p className="text-sm text-muted-foreground">
                You don’t have a clinic yet.
              </p>
              <Button
                className="w-full rounded-[6px]"
                onClick={() => router.push("/onboarding/create-clinic")}
              >
                Create clinic
              </Button>
            </div>
          ) : (
            tenants.map((t) => (
              <button
                key={t.slug}
                type="button"
                disabled={Boolean(busy)}
                onClick={() => void choose(t.slug)}
                className="flex w-full items-center justify-between rounded-[6px] border border-border px-3 py-3 text-left text-sm hover:bg-muted disabled:opacity-60"
              >
                <span>
                  <span className="font-medium">{t.name}</span>
                  <span className="mt-0.5 block text-xs text-muted-foreground">
                    {t.slug} · {t.status}
                  </span>
                </span>
                <span className="text-xs text-primary">
                  {busy === t.slug ? "Opening…" : "Open"}
                </span>
              </button>
            ))
          )}
        </div>
      </div>
    </div>
  );
}

export default function SelectTenantPage() {
  return (
    <ProtectedRoute>
      <Suspense fallback={<div className="p-8 text-center text-sm">Loading…</div>}>
        <SelectTenantInner />
      </Suspense>
    </ProtectedRoute>
  );
}
