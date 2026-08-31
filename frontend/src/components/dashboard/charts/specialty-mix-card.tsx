"use client";

import { InsightCard } from "@/components/dashboard/insights/insight-card";
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
          <h2 className="text-[15px] font-semibold tracking-[-0.02em] text-[#152038]">
            Appointments by specialty
          </h2>
          <p className="mt-0.5 text-[12px] leading-relaxed text-[#6B7280]">
            Top specialties from booked visits
          </p>
        </div>
        {more > 0 ? (
          <span className="shrink-0 pt-0.5 text-[11px] tabular-nums text-[#8B95A7]">
            +{more} more
          </span>
        ) : null}
      </div>

      {isLoading ? (
        <div className="mt-5 space-y-2">
          {Array.from({ length: 5 }).map((_, i) => (
            <div key={i} className="h-12 animate-pulse rounded-[12px] bg-[#EEF2F7]" />
          ))}
        </div>
      ) : isError ? (
        <div className="mt-5 flex h-[240px] flex-col items-center justify-center text-center">
          <p className="text-sm font-medium text-[#152038]">Unable to load specialties</p>
          {onRetry ? (
            <button
              type="button"
              onClick={onRetry}
              className="mt-2 text-[13px] font-medium text-[#1E4D8C] hover:underline"
            >
              Try again
            </button>
          ) : null}
        </div>
      ) : !hasData ? (
        <div className="mt-5 flex h-[240px] flex-col items-center justify-center px-4 text-center">
          <p className="text-sm font-medium text-[#152038]">No specialty mix yet</p>
          <p className="mt-1 max-w-[240px] text-[13px] leading-relaxed text-[#6B7280]">
            Appointments linked to providers with specialties will show here.
          </p>
        </div>
      ) : (
        <ol className="mt-5 space-y-2">
          {rows.map((row, index) => {
            const share = Math.round((row.count / total) * 100);
            const width = Math.max(8, Math.round((row.count / max) * 100));
            return (
                  <li key={row.label} className="relative overflow-hidden rounded-[12px] bg-muted/40">
                <div
                  className="absolute inset-y-0 left-0 bg-primary/10"
                  style={{ width: `${width}%` }}
                  aria-hidden
                />
                <div className="relative flex items-center gap-3 px-4 py-3">
                  <span className="w-5 shrink-0 text-[11px] font-medium tabular-nums text-[#8B95A7]">
                    {String(index + 1).padStart(2, "0")}
                  </span>
                  <span className="min-w-0 flex-1 truncate text-[13px] font-medium text-[#152038]">
                    {row.label}
                  </span>
                  <span className="shrink-0 text-[15px] font-semibold tabular-nums tracking-[-0.03em] text-[#152038]">
                    {row.count.toLocaleString()}
                  </span>
                  <span className="w-10 shrink-0 text-right text-[11px] tabular-nums text-[#8B95A7]">
                    {share}%
                  </span>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </InsightCard>
  );
}
