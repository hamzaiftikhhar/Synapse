"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { cn } from "@/lib/utils";

export type StatusCount = {
  status: string;
  label: string;
  count: number;
  barClass: string;
};

export function StatusBreakdownCard({
  title,
  subtitle,
  counts,
}: {
  title: string;
  subtitle?: string;
  counts: StatusCount[];
}) {
  const total = counts.reduce((sum, c) => sum + c.count, 0);
  const rows = counts.filter((c) => c.count > 0);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {subtitle ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </CardHeader>
      <CardContent>
        {total === 0 ? (
          <div className="flex h-44 flex-col items-center justify-center gap-1 text-center">
            <p className="text-sm font-medium text-navy">No appointments yet</p>
            <p className="text-xs text-muted-foreground">
              Status breakdown appears once appointments come in.
            </p>
          </div>
        ) : (
          <ul className="space-y-3">
            {rows.map((row) => (
              <li key={row.status}>
                <div className="mb-1.5 flex items-baseline justify-between gap-3">
                  <span className="text-[13px] text-foreground">{row.label}</span>
                  <span className="text-[13px] font-medium tabular-nums text-navy">
                    {row.count}
                  </span>
                </div>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div
                    className={cn("h-full rounded-full", row.barClass)}
                    style={{ width: `${Math.max((row.count / total) * 100, 4)}%` }}
                  />
                </div>
              </li>
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
