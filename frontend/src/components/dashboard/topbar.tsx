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
import { DashboardSidebar } from "@/components/dashboard/sidebar";
import { useAuth } from "@/providers/auth-provider";

export function DashboardTopbar() {
  const { user, clinic, canExitClinic, logout } = useAuth();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const isSuper = user?.role === "SUPER_ADMIN";
  const inClinicAsSuper = isSuper && Boolean(clinic) && canExitClinic;

  function handleLogout() {
    logout();
    router.replace("/login");
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
        <div className="min-w-0">
          {inClinicAsSuper ? (
            <div className="leading-tight">
              <p className="text-[10px] font-medium uppercase tracking-wide text-muted-foreground">
                Platform → Viewing clinic
              </p>
              <p className="truncate text-sm font-medium text-foreground">
                {clinic?.name}
              </p>
            </div>
          ) : (
            <p className="text-sm text-muted-foreground">
              {clinic?.name ?? (isSuper ? "Platform" : "Workspace")}
            </p>
          )}
        </div>
      </div>

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
          {isSuper && !inClinicAsSuper ? (
            <DropdownMenuItem
              onClick={() => router.push("/dashboard/platform/settings")}
            >
              Platform settings
            </DropdownMenuItem>
          ) : (
            <DropdownMenuItem onClick={() => router.push("/dashboard/settings")}>
              Settings
            </DropdownMenuItem>
          )}
          {isSuper ? (
            <DropdownMenuItem
              onClick={() => router.push("/dashboard/platform")}
            >
              Platform overview
            </DropdownMenuItem>
          ) : null}
          <DropdownMenuSeparator />
          <DropdownMenuItem onClick={handleLogout}>
            <LogOut className="size-3.5" />
            Log out
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
    </header>
  );
}
