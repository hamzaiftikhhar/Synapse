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
  ClipboardList,
  Clock,
  CreditCard,
  LayoutDashboard,
  LifeBuoy,
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
  ClipboardList,
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
    <aside className="flex h-full w-64 flex-col border-r border-border bg-sidebar">
      <div className="flex h-14 items-center gap-2.5 border-b border-border px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary text-sm font-bold text-primary-foreground shadow-sm shadow-primary/30">
          S
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight text-navy">
            {APP_NAME}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {showPlatformNav ? "Platform" : clinic?.name ?? "Clinic portal"}
          </p>
        </div>
      </div>
      <ScrollArea className="flex-1 px-3 py-4">
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
                  "relative flex items-center gap-2.5 rounded-xl px-3 py-2.5 text-[13px] font-medium transition-colors",
                  active
                    ? "bg-accent text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                )}
              >
                {active ? (
                  <span className="absolute top-1/2 -left-3 h-4 w-1 -translate-y-1/2 rounded-full bg-primary" />
                ) : null}
                <Icon
                  className={cn(
                    "size-4 shrink-0",
                    active ? "opacity-100" : "opacity-70"
                  )}
                />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </ScrollArea>
      <div className="p-3">
        <Link
          href="/contact"
          className="group flex items-center gap-3 rounded-2xl border border-border bg-muted/40 px-3.5 py-3 transition-colors hover:border-primary/30 hover:bg-accent/60"
        >
          <div className="flex size-8 shrink-0 items-center justify-center rounded-xl bg-primary/12 text-primary">
            <LifeBuoy className="size-4" />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-navy">Help Center</p>
            <p className="truncate text-[11px] text-muted-foreground">
              Reach the Synapse team
            </p>
          </div>
        </Link>
      </div>
    </aside>
  );
}
