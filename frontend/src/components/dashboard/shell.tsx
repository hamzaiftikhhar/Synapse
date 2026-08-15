import type { LucideIcon } from "lucide-react";
import { Inbox } from "lucide-react";
import type { ReactNode } from "react";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export function DataTableShell({
  title,
  toolbar,
  children,
}: {
  title?: string;
  toolbar?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      {(title || toolbar) && (
        <CardHeader
          className={cn(
            "space-y-0 border-b border-border py-3",
            title
              ? "flex flex-row items-center justify-between gap-3"
              : "block"
          )}
        >
          {title ? (
            <CardTitle className="text-sm font-medium">{title}</CardTitle>
          ) : null}
          {toolbar}
        </CardHeader>
      )}
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

export function EmptyState({
  title,
  description,
  action,
  icon: Icon = Inbox,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  icon?: LucideIcon;
}) {
  return (
    <div className="flex flex-col items-center justify-center px-6 py-16 text-center">
      <div className="flex size-11 items-center justify-center rounded-full bg-muted text-muted-foreground">
        <Icon className="size-5" />
      </div>
      <p className="mt-3 text-sm font-medium text-navy">{title}</p>
      {description ? (
        <p className="mt-1 max-w-sm text-sm text-muted-foreground">{description}</p>
      ) : null}
      {action ? <div className="mt-4">{action}</div> : null}
    </div>
  );
}

export function TodoBackendNotice({ feature }: { feature: string }) {
  return (
    <div className="rounded-2xl border border-dashed border-border bg-muted/40 px-5 py-8">
      <p className="text-sm font-medium text-navy">{feature}</p>
      <p className="mt-2 text-sm text-muted-foreground">
        <span className="font-mono text-xs text-primary">
          TODO: Backend endpoint required
        </span>
        {" — "}
        This page is ready on the frontend. Wire the Django Ninja route, then
        connect the React Query hook.
      </p>
    </div>
  );
}
