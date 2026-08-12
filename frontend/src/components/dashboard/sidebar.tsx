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
  const showPlatformNav = isSuper && (!clinic || onPlatformRoute);
  const nav = showPlatformNav ? PLATFORM_NAV : DASHBOARD_NAV;

  return (
    <aside className="flex h-full w-64 flex-col border-r border-white/10 bg-[#1a1e26] text-[#e8eaef]">
      <div className="flex h-14 items-center gap-2.5 border-b border-white/10 px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-[#5c67f2] text-sm font-bold text-white">
          S
        </div>
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold tracking-tight text-white">
            {APP_NAME}
          </p>
          <p className="truncate text-[11px] text-white/45">
            {showPlatformNav ? "Platform" : clinic?.name ?? "Clinic portal"}
          </p>
        </div>
      </div>
      <ScrollArea className="flex-1 px-3 py-4">
        <nav className="space-y-0.5">
          {showPlatformNav ? (
            <p className="mb-2 px-2.5 text-[10px] font-semibold uppercase tracking-wide text-white/35">
              Platform
            </p>
          ) : clinic && isSuper ? (
            <p className="mb-2 px-2.5 text-[10px] font-semibold uppercase tracking-wide text-white/35">
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
                  "flex items-center gap-2.5 rounded-lg px-3 py-2.5 text-[13px] font-medium",
                  active
                    ? "bg-white/10 text-white"
                    : "text-white/55 hover:bg-white/5 hover:text-white/90"
                )}
              >
                <Icon
                  className="size-4 shrink-0"
                  strokeWidth={1.75}
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
          className="flex items-center gap-3 rounded-2xl border border-white/10 bg-white/5 px-3.5 py-3 hover:bg-white/10"
        >
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-white/10 text-white/80">
            <LifeBuoy className="size-4" strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-white">Help Center</p>
            <p className="truncate text-[11px] text-white/45">
              Reach the Synapse team
            </p>
          </div>
        </Link>
      </div>
    </aside>
  );
}
