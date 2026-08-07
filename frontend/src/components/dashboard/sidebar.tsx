"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  BookOpen,
  Bot,
  BriefcaseMedical,
  Building2,
  Calendar,
  Clock,
  CreditCard,
  LayoutDashboard,
  Settings,
  Shield,
  Stethoscope,
  Tags,
  User,
  Users,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { APP_NAME, DASHBOARD_NAV, PLATFORM_NAV } from "@/constants";
import { useAuth } from "@/providers/auth-provider";
import { ScrollArea } from "@/components/ui/scroll-area";

const ICONS: Record<string, LucideIcon> = {
  LayoutDashboard,
  Building2,
  Stethoscope,
  BriefcaseMedical,
  Tags,
  Shield,
  Clock,
  Calendar,
  Users,
  BookOpen,
  Bot,
  BarChart3,
  CreditCard,
  Settings,
  User,
};

export function DashboardSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { clinic, user } = useAuth();
  const isSuper = user?.role === "SUPER_ADMIN";
  const onPlatformRoute = pathname.startsWith("/dashboard/platform");
  // Platform portal: Super Admin with no clinic, or browsing platform while switching
  const showPlatformNav = isSuper && (!clinic || onPlatformRoute);
  const nav = showPlatformNav ? PLATFORM_NAV : DASHBOARD_NAV;

  return (
    <aside className="flex h-full w-60 flex-col border-r border-border bg-sidebar">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="flex size-7 items-center justify-center rounded-xl bg-navy text-xs font-bold text-white">
          S
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight text-navy">
            {APP_NAME}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {showPlatformNav
              ? "Platform"
              : clinic?.name ?? "Clinic portal"}
          </p>
        </div>
      </div>
      <ScrollArea className="flex-1 px-2 py-3">
        <nav className="space-y-0.5">
          {showPlatformNav ? (
            <p className="mb-2 px-2.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Platform
            </p>
          ) : clinic && isSuper ? (
            <p className="mb-2 px-2.5 text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Clinic portal
            </p>
          ) : null}
          {nav.map((item) => {
            const Icon = ICONS[item.icon] ?? LayoutDashboard;
            const active =
              item.href === "/dashboard" || item.href === "/dashboard/platform"
                ? pathname === item.href
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                className={cn(
                  "flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-accent text-accent-foreground"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                <Icon className="size-4 shrink-0 opacity-80" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </ScrollArea>
    </aside>
  );
}
