"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { Building2, Check, ChevronsUpDown, LogOut, Search } from "lucide-react";
import { toast } from "sonner";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuSub,
  DropdownMenuSubContent,
  DropdownMenuSubTrigger,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Input } from "@/components/ui/input";
import { usePlatformClinics } from "@/hooks/api";
import { useAuth } from "@/providers/auth-provider";
import { useWorkspaceHandoff } from "@/providers/workspace-handoff-provider";
import { getApiErrorMessage } from "@/lib/api/client";
import { cn } from "@/lib/utils";

function clinicHomePath(status: string): string {
  return status === "onboarding" ? "/onboarding" : "/dashboard";
}

/**
 * Super Admin clinic context — one control for the active tenant.
 * "All clinics" opens a searchable flyout so you can switch workspaces
 * without bouncing through the platform clinics page (and getting stuck
 * still entered into a clinic).
 */
export function WorkspaceSwitcher({ className }: { className?: string }) {
  const { user, clinic, canExitClinic, enterClinic, exitClinic } = useAuth();
  const { beginHandoff } = useWorkspaceHandoff();
  const router = useRouter();
  const [exiting, setExiting] = useState(false);
  const [switchingSlug, setSwitchingSlug] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [menuOpen, setMenuOpen] = useState(false);

  const isSuperInClinic =
    user?.role === "SUPER_ADMIN" && Boolean(clinic) && canExitClinic;

  const { data: clinics, isLoading } = usePlatformClinics("", menuOpen && isSuperInClinic);

  const filtered = useMemo(() => {
    const rows = clinics ?? [];
    const q = query.trim().toLowerCase();
    if (!q) return rows;
    return rows.filter(
      (c) =>
        c.name.toLowerCase().includes(q) ||
        c.slug.toLowerCase().includes(q) ||
        (c.email || "").toLowerCase().includes(q)
    );
  }, [clinics, query]);

  if (!isSuperInClinic || !clinic) {
    return null;
  }

  async function handleExit() {
    setExiting(true);
    setMenuOpen(false);
    try {
      await beginHandoff({
        label: "Returning to platform",
        href: "/dashboard/platform",
        successToast: "Returned to platform",
        navigation: "soft",
        run: () => exitClinic(),
      });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
      setExiting(false);
    }
  }

  async function handleSwitch(slug: string, status: string, name: string) {
    if (!clinic || slug === clinic.slug) {
      setMenuOpen(false);
      return;
    }
    setSwitchingSlug(slug);
    setMenuOpen(false);
    setQuery("");
    try {
      await beginHandoff({
        label: `Opening ${name}`,
        href: clinicHomePath(status),
        navigation: "soft",
        run: async () => {
          const data = await enterClinic(slug);
          const nextName = data.clinic?.name ?? name;
          return {
            href: clinicHomePath(data.clinic?.status ?? status),
            successToast: `Switched to ${nextName}`,
          };
        },
      });
    } catch (err) {
      toast.error(getApiErrorMessage(err));
      setSwitchingSlug(null);
    }
  }

  return (
    <DropdownMenu
      open={menuOpen}
      onOpenChange={(open) => {
        setMenuOpen(open);
        if (!open) {
          setQuery("");
          setSwitchingSlug(null);
        }
      }}
    >
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

        <DropdownMenuSub>
          <DropdownMenuSubTrigger className="gap-1.5">
            All clinics
          </DropdownMenuSubTrigger>
          <DropdownMenuSubContent
            className="w-72 p-0"
            side="right"
            align="start"
            sideOffset={6}
          >
            <div
              className="border-b border-border p-2"
              onKeyDown={(e) => e.stopPropagation()}
              onPointerDown={(e) => e.stopPropagation()}
              onClick={(e) => e.stopPropagation()}
            >
              <div className="relative">
                <Search className="pointer-events-none absolute left-2.5 top-1/2 size-3.5 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  placeholder="Search clinics…"
                  className="h-8 rounded-md pl-8 text-xs"
                  aria-label="Search clinics"
                />
              </div>
            </div>
            <div className="max-h-64 overflow-y-auto p-1">
              {isLoading ? (
                <p className="px-2 py-3 text-center text-xs text-muted-foreground">
                  Loading clinics…
                </p>
              ) : filtered.length === 0 ? (
                <p className="px-2 py-3 text-center text-xs text-muted-foreground">
                  {query.trim() ? "No matching clinics" : "No clinics yet"}
                </p>
              ) : (
                filtered.map((row) => {
                  const isCurrent = row.slug === clinic.slug;
                  const busy = switchingSlug === row.slug;
                  return (
                    <DropdownMenuItem
                      key={row.id}
                      disabled={Boolean(switchingSlug)}
                      closeOnClick={false}
                      onClick={() => {
                        if (switchingSlug) return;
                        void handleSwitch(row.slug, row.status, row.name);
                      }}
                      className="items-start gap-2 py-2"
                    >
                      <span className="mt-0.5 flex size-6 shrink-0 items-center justify-center rounded-md bg-muted text-muted-foreground">
                        <Building2 className="size-3.5" strokeWidth={1.75} />
                      </span>
                      <span className="min-w-0 flex-1">
                        <span className="block truncate text-sm font-medium text-foreground">
                          {busy ? "Switching…" : row.name}
                        </span>
                        <span className="block truncate text-xs text-muted-foreground">
                          {row.slug}
                          {row.status !== "active" ? ` · ${row.status}` : ""}
                        </span>
                      </span>
                      {isCurrent ? (
                        <Check className="mt-0.5 size-3.5 shrink-0 text-primary" />
                      ) : null}
                    </DropdownMenuItem>
                  );
                })
              )}
            </div>
          </DropdownMenuSubContent>
        </DropdownMenuSub>

        <DropdownMenuItem disabled={exiting} onClick={() => void handleExit()}>
          <LogOut className="size-3.5" />
          {exiting ? "Leaving…" : "Back to platform"}
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
