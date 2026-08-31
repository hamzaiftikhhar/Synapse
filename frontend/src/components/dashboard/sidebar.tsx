"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  BarChart3,
  BookOpen,
  Bot,
  BriefcaseMedical,
  Building2,
  Calendar,
  ChevronDown,
  ClipboardList,
  Clock,
  CreditCard,
  LayoutDashboard,
  LifeBuoy,
  MessageSquare,
  Settings,
  Shield,
  Stethoscope,
  Tags,
  Users,
  X,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";
import {
  APP_NAME,
  DASHBOARD_NAV,
  PLATFORM_NAV,
  isNavHrefActive,
  navGroupContainsPath,
  type DashboardNavGroup,
  type DashboardNavItem,
} from "@/constants";
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
  MessageSquare,
  BarChart3,
  CreditCard,
  Settings,
};

const OPEN_GROUPS_KEY = "synapse_sidebar_groups";

function readOpenGroups(): Record<string, boolean> {
  if (typeof window === "undefined") return {};
  try {
    const raw = sessionStorage.getItem(OPEN_GROUPS_KEY);
    return raw ? (JSON.parse(raw) as Record<string, boolean>) : {};
  } catch {
    return {};
  }
}

function writeOpenGroups(value: Record<string, boolean>) {
  try {
    sessionStorage.setItem(OPEN_GROUPS_KEY, JSON.stringify(value));
  } catch {
    /* ignore quota / private mode */
  }
}

function NavLink({
  item,
  pathname,
  onNavigate,
}: {
  item: DashboardNavItem;
  pathname: string;
  onNavigate?: () => void;
}) {
  const Icon = ICONS[item.icon] ?? LayoutDashboard;
  const active = isNavHrefActive(item.href, pathname);
  return (
    <Link
      href={item.href}
      onClick={onNavigate}
      className={cn(
        "flex items-center gap-2.5 rounded-lg px-3 py-2 text-[13px] font-medium",
        active
          ? "bg-sidebar-accent text-sidebar-accent-foreground"
          : "text-sidebar-foreground/55 hover:bg-sidebar-accent/70 hover:text-sidebar-foreground"
      )}
    >
      <Icon className="size-4 shrink-0" strokeWidth={1.75} />
      {item.label}
    </Link>
  );
}

function NavSection({
  group,
  pathname,
  onNavigate,
  forcedOpen,
  openOverride,
  onToggle,
}: {
  group: DashboardNavGroup;
  pathname: string;
  onNavigate?: () => void;
  forcedOpen: boolean;
  openOverride?: boolean;
  onToggle?: (id: string, next: boolean) => void;
}) {
  const collapsible = Boolean(group.collapsible);
  const open = !collapsible || forcedOpen || Boolean(openOverride);
  const divided = group.id === "workspace" || group.id === "admin";

  return (
    <div
      data-nav-group={group.id}
      className={divided ? "border-t border-sidebar-border pt-4" : undefined}
    >
      {collapsible ? (
        <button
          type="button"
          aria-expanded={open}
          onClick={() => onToggle?.(group.id, !open)}
          className="mb-1 flex w-full items-center justify-between rounded-md px-2.5 py-1 text-left text-[10px] font-semibold tracking-wide text-sidebar-foreground/40 uppercase hover:text-sidebar-foreground/70"
        >
          {group.label}
          <ChevronDown
            className={cn(
              "size-3.5 shrink-0 transition-transform duration-200",
              open ? "rotate-0" : "-rotate-90"
            )}
            strokeWidth={2}
          />
        </button>
      ) : (
        <p className="mb-1 px-2.5 text-[10px] font-semibold tracking-wide text-sidebar-foreground/40 uppercase">
          {group.label}
        </p>
      )}
      <div
        className={cn(
          "grid transition-[grid-template-rows] duration-200 ease-out motion-reduce:transition-none",
          open ? "grid-rows-[1fr]" : "grid-rows-[0fr]"
        )}
      >
        <div
          className={cn(
            "min-h-0 overflow-hidden",
            !open && "invisible pointer-events-none"
          )}
          inert={!open || undefined}
        >
          <div className="space-y-0.5 pb-0.5">
            {group.items.map((item) => (
              <NavLink
                key={item.href}
                item={item}
                pathname={pathname}
                onNavigate={onNavigate}
              />
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

export function DashboardSidebar({ onNavigate }: { onNavigate?: () => void }) {
  const pathname = usePathname();
  const { clinic, user } = useAuth();
  const isSuper = user?.role === "SUPER_ADMIN";
  const onPlatformRoute = pathname.startsWith("/dashboard/platform");
  const showPlatformNav = isSuper && (!clinic || onPlatformRoute);
  const nav = showPlatformNav ? PLATFORM_NAV : DASHBOARD_NAV;
  const [openGroups, setOpenGroups] = useState<Record<string, boolean>>({});

  useEffect(() => {
    setOpenGroups(readOpenGroups());
  }, []);

  function toggleGroup(id: string, next: boolean) {
    setOpenGroups((prev) => {
      const updated = { ...prev, [id]: next };
      writeOpenGroups(updated);
      return updated;
    });
  }

  return (
    <aside
      data-testid="dashboard-sidebar"
      className="flex h-full w-full flex-col border-r border-sidebar-border bg-sidebar text-sidebar-foreground lg:w-64"
    >
      <div className="flex h-14 items-center gap-2.5 border-b border-sidebar-border px-4">
        <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-primary text-sm font-bold text-sidebar-primary-foreground">
          S
        </div>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-semibold tracking-tight text-sidebar-foreground">
            {APP_NAME}
          </p>
          <p className="truncate text-[11px] text-sidebar-foreground/45">
            {showPlatformNav ? "Platform" : clinic?.name ?? "Clinic portal"}
          </p>
        </div>
        {onNavigate ? (
          <button
            type="button"
            onClick={onNavigate}
            aria-label="Close menu"
            className="inline-flex size-8 shrink-0 items-center justify-center rounded-lg text-sidebar-foreground/70 hover:bg-sidebar-accent hover:text-sidebar-foreground lg:hidden"
          >
            <X className="size-4" strokeWidth={1.75} />
          </button>
        ) : null}
      </div>
      <ScrollArea className="flex-1 px-3 py-4">
        <nav
          aria-label={showPlatformNav ? "Platform" : "Clinic portal"}
          className="space-y-4"
        >
          {nav.map((group) => {
            const containsActive = navGroupContainsPath(group, pathname);
            const stored = openGroups[group.id];
            const defaultOpen = group.defaultOpen !== false;
            const userOpen = stored === undefined ? defaultOpen : stored;
            return (
              <NavSection
                key={group.id}
                group={group}
                pathname={pathname}
                onNavigate={onNavigate}
                forcedOpen={containsActive}
                openOverride={userOpen}
                onToggle={toggleGroup}
              />
            );
          })}
        </nav>
      </ScrollArea>
      <div className="p-3">
        <Link
          href="/contact"
          className="flex items-center gap-3 rounded-xl border border-sidebar-border bg-sidebar-accent/50 px-3.5 py-3 hover:bg-sidebar-accent"
        >
          <div className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-sidebar-accent text-sidebar-foreground/80">
            <LifeBuoy className="size-4" strokeWidth={1.75} />
          </div>
          <div className="min-w-0">
            <p className="text-[13px] font-medium text-sidebar-foreground">
              Help Center
            </p>
            <p className="truncate text-[11px] text-sidebar-foreground/45">
              Reach the Synapse team
            </p>
          </div>
        </Link>
      </div>
    </aside>
  );
}
