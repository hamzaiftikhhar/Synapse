"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, ChevronsUpDown, LayoutGrid, LogOut } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { useAuth } from "@/providers/auth-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";

/**
 * Super Admin clinic context — one control for the active tenant.
 * Replaces the old topbar label + yellow banner duplication.
 */
export function WorkspaceSwitcher({ className }: { className?: string }) {
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
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Switch workspace"
        className={cn(
          "inline-flex h-9 max-w-[min(100%,280px)] items-center gap-2 rounded-lg border border-border bg-background px-2.5 text-sm transition-colors hover:bg-muted",
          className
        )}
      >
        <span className="flex size-6 shrink-0 items-center justify-center rounded-md bg-primary/10 text-primary">
          <Building2 className="size-3.5" strokeWidth={1.75} />
        </span>
        <span className="min-w-0 truncate font-medium text-foreground">
          {clinic.name}
        </span>
        <ChevronsUpDown className="size-3.5 shrink-0 text-muted-foreground" />
      </DropdownMenuTrigger>
      <DropdownMenuContent align="start" className="w-64">
        <DropdownMenuLabel className="font-normal">
          <p className="truncate text-sm font-medium text-foreground">{clinic.name}</p>
          <p className="text-xs text-muted-foreground">Clinic workspace · super admin</p>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        {clinic.status === "onboarding" ? (
          <DropdownMenuItem onClick={() => router.push("/onboarding")}>
            Continue clinic setup
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuItem onClick={() => router.push("/dashboard/platform/clinics")}>
          <LayoutGrid className="size-3.5" />
          All clinics
        </DropdownMenuItem>
        <DropdownMenuItem disabled={exiting} onClick={() => void handleExit()}>
          <LogOut className="size-3.5" />
          {exiting ? "Leaving…" : "Back to platform"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
