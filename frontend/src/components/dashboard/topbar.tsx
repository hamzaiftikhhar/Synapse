"use client";

import { useRouter } from "next/navigation";
import { LogOut, Menu, User } from "lucide-react";
import { useState } from "react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Sheet, SheetContent, SheetTrigger } from "@/components/ui/sheet";
import { Button } from "@/components/ui/button";
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { useAuth } from "@/providers/auth-provider";
import { toast } from "sonner";
import { getApiErrorMessage } from "@/lib/api/client";

export function DashboardTopbar() {
  const { user, clinic, canExitClinic, exitClinic, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [exiting, setExiting] = useState(false);

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  async function handleExit() {
    setExiting(true);
    try {
      await exitClinic();
      toast.success("Exited clinic context");
      router.push("/dashboard/platform");
    } catch (err) {
      toast.error(getApiErrorMessage(err));
    } finally {
      setExiting(false);
    }
  }

  return (
    <header className="flex h-14 items-center justify-between border-b border-border bg-white px-4 lg:px-6">
      <div className="flex items-center gap-2">
        <Sheet open={open} onOpenChange={setOpen}>
          <SheetTrigger
            className="inline-flex size-8 items-center justify-center rounded-[6px] border border-transparent hover:bg-muted lg:hidden"
            aria-label="Open menu"
          >
            <Menu className="size-4" />
          </SheetTrigger>
          <SheetContent side="left" className="w-60 p-0">
            <DashboardSidebar onNavigate={() => setOpen(false)} />
          </SheetContent>
        </Sheet>
        <p className="text-sm text-muted-foreground">
          {clinic?.name ??
            (user?.role === "SUPER_ADMIN" ? "Platform" : "Workspace")}
        </p>
        {user?.role === "SUPER_ADMIN" && clinic ? (
          <span className="rounded bg-amber-50 px-1.5 py-0.5 text-[10px] font-medium uppercase tracking-wide text-amber-800">
            Super Admin view
          </span>
        ) : null}
      </div>

      <div className="flex items-center gap-2">
        {user?.role === "SUPER_ADMIN" ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="hidden rounded-[6px] sm:inline-flex"
            onClick={() => router.push("/dashboard/platform")}
          >
            {canExitClinic ? "Switch clinic" : "Platform"}
          </Button>
        ) : null}
        {canExitClinic ? (
          <Button
            type="button"
            variant="outline"
            size="sm"
            className="rounded-[6px]"
            disabled={exiting}
            onClick={() => void handleExit()}
          >
            {exiting ? "Exiting…" : "Exit clinic"}
          </Button>
        ) : null}

        <DropdownMenu>
          <DropdownMenuTrigger className="inline-flex h-8 items-center gap-2 rounded-[6px] border border-border bg-background px-2.5 text-sm hover:bg-muted">
            <User className="size-3.5" />
            <span className="hidden sm:inline">
              {user?.first_name || user?.email}
            </span>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-52 rounded-[6px]">
            <DropdownMenuLabel className="font-normal">
              <div className="flex flex-col gap-0.5">
                <span className="text-sm font-medium">
                  {user?.first_name} {user?.last_name}
                </span>
                <span className="text-xs text-muted-foreground">{user?.email}</span>
                <span className="text-[10px] uppercase text-muted-foreground">
                  {user?.role}
                </span>
              </div>
            </DropdownMenuLabel>
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={() => router.push("/dashboard/profile")}>
              Profile
            </DropdownMenuItem>
            <DropdownMenuItem onClick={() => router.push("/dashboard/settings")}>
              Settings
            </DropdownMenuItem>
            {user?.role === "SUPER_ADMIN" ? (
              <DropdownMenuItem
                onClick={() => router.push("/dashboard/platform")}
              >
                Platform
              </DropdownMenuItem>
            ) : null}
            <DropdownMenuSeparator />
            <DropdownMenuItem onClick={handleLogout}>
              <LogOut className="size-3.5" />
              Log out
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </header>
  );
}
