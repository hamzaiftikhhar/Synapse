"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";

/** Persistent banner when Super Admin is operating inside a clinic tenant. */
export function ViewingClinicBanner() {
  const { user, clinic, canExitClinic, exitClinic } = useAuth();
  const router = useRouter();
  const [exiting, setExiting] = useState(false);

  if (user?.role !== "SUPER_ADMIN" || !clinic || !canExitClinic) {
    return null;
  }

  async function handleExit() {
    setExiting(true);
    try {
      await exitClinic();
      toast.success("Returned to platform");
      router.push("/dashboard/platform");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setExiting(false);
    }
  }

  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-b border-warning/25 bg-warning/10 px-4 py-2.5 lg:px-6">
      <div className="min-w-0">
        <p className="text-[10px] font-semibold uppercase tracking-wide text-warning">
          Viewing clinic
        </p>
        <p className="truncate text-sm font-semibold text-foreground">
          {clinic.name}
          <span className="ml-2 font-normal text-muted-foreground">
            You are operating as Super Admin.
          </span>
        </p>
      </div>
      <div className="flex shrink-0 gap-2">
        <Button
          type="button"
          variant="outline"
          size="sm"
          className="border-warning/40 bg-card"
          onClick={() => router.push("/dashboard/platform/clinics")}
        >
          Switch clinic
        </Button>
        <Button
          type="button"
          size="sm"
          disabled={exiting}
          onClick={() => void handleExit()}
        >
          {exiting ? "Exiting…" : "Exit clinic"}
        </Button>
      </div>
    </div>
  );
}
