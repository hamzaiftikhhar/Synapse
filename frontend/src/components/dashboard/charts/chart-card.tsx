"use client";

import type { ReactNode } from "react";
import { InsightCard } from "@/components/dashboard/insights/insight-card";
import { cn } from "@/lib/utils";

export function ChartCard({
  title,
  description,
  action,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <InsightCard overflow="visible" className={cn("p-5", className)}>
      <div className="mb-4 flex items-start justify-between gap-3">
        <div>
          <p className="text-[15px] font-medium text-navy">{title}</p>
          {description ? (
            <p className="mt-0.5 text-[12px] text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {action}
      </div>
      {children}
    </InsightCard>
  );
}

export function ChartEmptyState({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex h-[240px] flex-col items-center justify-center px-6 text-center">
      <p className="text-sm font-medium text-navy">{title}</p>
      <p className="mt-1 max-w-sm text-[13px] text-muted-foreground">{description}</p>
    </div>
  );
}

export function ChartSkeleton({ className }: { className?: string }) {
  return (
    <div
      className={cn("h-[240px] animate-pulse rounded-[10px] bg-muted/70", className)}
      aria-hidden
    />
  );
}

export function ChartErrorState({ onRetry }: { onRetry?: () => void }) {
  return (
    <div className="flex h-[240px] flex-col items-center justify-center gap-2 text-center">
      <p className="text-sm font-medium text-navy">Unable to load analytics</p>
      {onRetry ? (
        <button
          type="button"
          onClick={onRetry}
          className="text-[13px] font-medium text-primary hover:underline"
        >
          Try again
        </button>
      ) : null}
    </div>
  );
}

export function ChartPanel({
  title,
  description,
  action,
  isLoading,
  isError,
  onRetry,
  hasData,
  emptyTitle,
  emptyDescription,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  isLoading?: boolean;
  isError?: boolean;
  onRetry?: () => void;
  hasData: boolean;
  emptyTitle: string;
  emptyDescription: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <ChartCard title={title} description={description} action={action} className={className}>
      {isLoading ? (
        <ChartSkeleton />
      ) : isError ? (
        <ChartErrorState onRetry={onRetry} />
      ) : !hasData ? (
        <ChartEmptyState title={emptyTitle} description={emptyDescription} />
      ) : (
        children
      )}
    </ChartCard>
  );
}
