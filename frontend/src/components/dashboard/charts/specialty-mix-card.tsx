"use client";

import { InsightCard } from "@/components/dashboard/insights/insight-card";
import { RankedBreakdownList } from "@/components/dashboard/charts/ranked-breakdown-list";
import { cn } from "@/lib/utils";
import type { AnalyticsNamedCount } from "@/types/api";

type Row = {
  label: string;
  count: number;
};

function normalize(data: AnalyticsNamedCount[] | undefined): Row[] {
  if (!Array.isArray(data)) return [];
  return data
    .map((row) => ({
      label: String(row?.label ?? "").trim(),
      count: Number(row?.count),
    }))
    .filter((row) => row.label && Number.isFinite(row.count) && row.count > 0);
}

export function SpecialtyMixCard({
  data,
  more = 0,
  isLoading,
  isError,
  onRetry,
  className,
}: {
  data: AnalyticsNamedCount[] | undefined;
  more?: number;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  className?: string;
}) {
  const rows = normalize(data);
  const total = rows.reduce((sum, row) => sum + row.count, 0);
  const max = rows.reduce((n, row) => Math.max(n, row.count), 0);
  const hasData = total > 0 && max > 0;

  return (
    <InsightCard overflow="hidden" className={cn("flex h-full p-6", className)}>
      <div className="flex items-start justify-between gap-3">
        <div>
          <h2 className="text-[15px] font-semibold tracking-tight text-foreground">
            Appointments by specialty
          </h2>
          <p className="mt-0.5 text-[12px] leading-relaxed text-muted-foreground">
            Top specialties from booked visits
          </p>
        </div>
        {more > 0 ? (
          <span className="shrink-0 pt-0.5 text-[11px] tabular-nums text-muted-foreground">
            +{more} more
          </span>
        ) : null}
      </div>

      {isLoading ? (
        <div className="mt-5 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-[12px] bg-muted/70" />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-5 flex h-[240px] flex-col items-center justify-center text-center">
          <p className="text-sm font-medium text-foreground">Unable to load specialties</p>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 text-[13px] font-medium text-primary hover:underline"
            >
              Try again
            </button>
          ) : null}
        </div>
      ) : !hasData ? (
        <div className="mt-5 flex h-[240px] flex-col items-center justify-center px-4 text-center">
          <p className="text-sm font-medium text-foreground">No specialty mix yet</p>
          <p className="mt-1 max-w-[240px] text-[13px] leading-relaxed text-muted-foreground">
            Appointments linked to providers with specialties will show here.
          </p>
        </div>
      ) : (
        <div className="mt-5">
          <RankedBreakdownList items={rows} />
        </div>
      )}
    </InsightCard>
  );
}
