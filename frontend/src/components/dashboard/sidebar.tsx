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
import { APP_NAME, DASHBOARD_NAV } from "@/constants";
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

  return (
    <aside className="flex h-full w-60 flex-col border-r border-border bg-sidebar">
      <div className="flex h-14 items-center gap-2 border-b border-border px-4">
        <div className="flex size-7 items-center justify-center rounded-[6px] bg-navy text-xs font-bold text-white">
          S
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight text-navy">
            {APP_NAME}
          </p>
          <p className="truncate text-[11px] text-muted-foreground">
            {clinic?.name ?? (isSuper ? "Platform" : "Clinic portal")}
          </p>
        </div>
      </div>
      <ScrollArea className="flex-1 px-2 py-3">
        <nav className="space-y-0.5">
          {isSuper ? (
            <Link
              href="/dashboard/platform"
              onClick={onNavigate}
              className={cn(
                "flex items-center gap-2.5 rounded-[6px] px-2.5 py-2 text-[13px] font-medium transition-colors",
                pathname.startsWith("/dashboard/platform")
                  ? "bg-primary/10 text-primary"
                  : "text-sidebar-foreground/80 hover:bg-muted hover:text-foreground"
              )}
            >
              <Building2 className="size-4 shrink-0 opacity-70" />
              Platform
            </Link>
          ) : null}
          {DASHBOARD_NAV.map((item) => {
            const Icon = ICONS[item.icon] ?? LayoutDashboard;
            const active =
              item.href === "/dashboard"
                ? pathname === "/dashboard"
                : pathname.startsWith(item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                onClick={onNavigate}
                className={cn(
                  "flex items-center gap-2.5 rounded-[6px] px-2.5 py-2 text-[13px] font-medium transition-colors",
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
