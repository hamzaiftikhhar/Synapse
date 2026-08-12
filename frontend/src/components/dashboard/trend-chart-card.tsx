"use client";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";

export type DailyPoint = { label: string; count: number };

export function TrendChartCard({
  title,
  subtitle,
  data,
  totalLabel,
  total,
}: {
  title: string;
  subtitle?: string;
  data: DailyPoint[];
  totalLabel: string;
  total: number;
}) {
  const hasData = data.some((d) => d.count > 0);
  const max = Math.max(...data.map((d) => d.count), 1);

  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
        {subtitle ? (
          <p className="mt-0.5 text-xs text-muted-foreground">{subtitle}</p>
        ) : null}
      </CardHeader>
      <CardContent>
        <div className="mb-4">
          <p className="text-xs text-muted-foreground">{totalLabel}</p>
          <p className="text-2xl font-semibold tracking-tight text-navy tabular-nums">
            {total}
          </p>
        </div>
        {!hasData ? (
          <div className="flex h-44 flex-col items-center justify-center gap-1 text-center">
            <p className="text-sm font-medium text-navy">Nothing booked yet</p>
            <p className="text-xs text-muted-foreground">
              New appointments in this window will show up here.
            </p>
          </div>
        ) : (
          <div className="flex h-44 items-end gap-1">
            {data.map((d) => {
              const pct = d.count === 0 ? 0 : Math.max((d.count / max) * 100, 8);
              return (
                <div
                  key={d.label}
                  className="flex min-w-0 flex-1 flex-col items-center gap-1.5"
                  title={`${d.label}: ${d.count} appointment${d.count === 1 ? "" : "s"}`}
                >
                  <div className="flex h-36 w-full items-end justify-center">
                    <div
                      className="w-full max-w-7 rounded-t-md bg-primary/90"
                      style={{ height: `${pct}%` }}
                    />
                  </div>
                  <span className="w-full truncate text-center text-[10px] leading-none text-muted-foreground">
                    {d.label}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
