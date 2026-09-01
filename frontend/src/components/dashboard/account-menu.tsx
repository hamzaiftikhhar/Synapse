"use client";

import { useRouter } from "next/navigation";
import { LogOut } from "lucide-react";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import { Avatar, AvatarFallback } from "@/components/ui/avatar";
import { Badge } from "@/components/ui/badge";
import { useAuth } from "@/providers/auth-provider";
import { roleLabel } from "@/features/platform/format";

function displayName(first?: string | null, last?: string | null, email?: string | null) {
  const full = [first?.trim(), last?.trim()].filter(Boolean).join(" ");
  if (full) return full;
  if (email) return email.split("@")[0] ?? email;
  return "Account";
}

function initials(first?: string | null, last?: string | null, email?: string | null) {
  const a = first?.trim()?.[0] ?? "";
  const b = last?.trim()?.[0] ?? "";
  if (a || b) return `${a}${b}`.toUpperCase();
  return (email?.[0] ?? "?").toUpperCase();
}

export function AccountMenu() {
  const { user, clinic, canExitClinic, logout } = useAuth();
  const router = useRouter();
  const isSuper = user?.role === "SUPER_ADMIN";
  const inClinicAsSuper = isSuper && Boolean(clinic) && canExitClinic;
  const name = displayName(user?.first_name, user?.last_name, user?.email);

  function handleLogout() {
    logout();
    router.replace("/login");
  }

  const workspaceLine = inClinicAsSuper
    ? null
    : isSuper
      ? "Synapse platform"
      : clinic?.name ?? null;

  return (
    <DropdownMenu>
      <DropdownMenuTrigger
        aria-label="Account menu"
        className="inline-flex h-9 items-center gap-2 rounded-lg border border-transparent py-1 pr-2 pl-1 text-sm transition-colors hover:border-border hover:bg-muted"
      >
        <Avatar size="sm" className="size-7">
          <AvatarFallback className="bg-primary text-[11px] font-semibold text-primary-foreground">
            {initials(user?.first_name, user?.last_name, user?.email)}
          </AvatarFallback>
        </Avatar>
        <span className="hidden max-w-[140px] truncate font-medium text-foreground sm:inline">
          {name}
        </span>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="space-y-2 font-normal">
          <div>
            <p className="truncate text-sm font-medium text-foreground">{name}</p>
            <p className="truncate text-xs text-muted-foreground">{user?.email}</p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            {user ? (
              <Badge variant="secondary" className="text-[10px] font-normal">
                {roleLabel(user.role)}
              </Badge>
            ) : null}
            {workspaceLine ? (
              <span className="max-w-full truncate text-[11px] text-muted-foreground">
                {workspaceLine}
              </span>
            ) : null}
          </div>
        </DropdownMenuLabel>
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={() => router.push("/dashboard/profile")}>
          Your account
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
          <DropdownMenuItem onClick={() => router.push("/dashboard/platform")}>
            Platform home
          </DropdownMenuItem>
        ) : null}
        <DropdownMenuSeparator />
        <DropdownMenuItem onClick={handleLogout}>
          <LogOut className="size-3.5" />
          Log out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
