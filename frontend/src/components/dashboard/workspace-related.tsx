import Link from "next/link";
import {
  Building2,
  Clock,
  Settings,
  User,
  type LucideIcon,
} from "lucide-react";
import { cn } from "@/lib/utils";

export type WorkspaceRelatedId =
  | "clinic"
  | "hours"
  | "settings"
  | "profile";

const LINKS: {
  id: WorkspaceRelatedId;
  href: string;
  title: string;
  description: string;
  icon: LucideIcon;
}[] = [
  {
    id: "clinic",
    href: "/dashboard/clinic",
    title: "Clinic profile",
    description: "Name, address, and public contact details",
    icon: Building2,
  },
  {
    id: "hours",
    href: "/dashboard/business-hours",
    title: "Business hours",
    description: "Weekly open and close times for booking",
    icon: Clock,
  },
  {
    id: "settings",
    href: "/dashboard/settings",
    title: "Workspace settings",
    description: "Booking rules, widget, and notifications",
    icon: Settings,
  },
  {
    id: "profile",
    href: "/dashboard/profile",
    title: "Your account",
    description: "Staff name, email, and password",
    icon: User,
  },
];

export function WorkspaceRelated({
  current,
  className,
}: {
  current: WorkspaceRelatedId;
  className?: string;
}) {
  const items = LINKS.filter((item) => item.id !== current);

  return (
    <section className={cn("mt-8", className)} aria-labelledby="related-heading">
      <h2
        id="related-heading"
        className="text-xs font-semibold tracking-wide text-muted-foreground uppercase"
      >
        Related
      </h2>
      <p className="mt-1 text-sm text-muted-foreground">
        Each of these lives in one place. Use the links when you need a
        different part of the workspace.
      </p>
      <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {items.map((item) => {
          const Icon = item.icon;
          return (
            <Link
              key={item.id}
              href={item.href}
              className="group rounded-xl bg-card p-4 ring-1 ring-foreground/6 transition-colors hover:bg-muted/60"
            >
              <div className="flex items-start gap-3">
                <span className="flex size-8 shrink-0 items-center justify-center rounded-lg bg-primary/10 text-primary">
                  <Icon className="size-4" strokeWidth={1.75} />
                </span>
                <div className="min-w-0">
                  <p className="text-sm font-medium text-foreground group-hover:text-primary">
                    {item.title}
                  </p>
                  <p className="mt-0.5 text-xs text-muted-foreground">
                    {item.description}
                  </p>
                </div>
              </div>
            </Link>
          );
        })}
      </div>
    </section>
  );
}
