"use client";

import type { ReactNode } from "react";
import { InsightCard } from "@/components/dashboard/insights/insight-card";
import { cn } from "@/lib/utils";

export function ChartCard({
  title,
  description,
  action,
  metrics,
  footer,
  children,
  className,
}: {
  title: string;
  description?: string;
  action?: ReactNode;
  /** Primary metric(s) rendered between the header and the chart — the
   * "metric → chart → drill-down" hierarchy: a number the chart explains,
   * not just decoration around it. */
  metrics?: ReactNode;
  /** Drill-down action (e.g. "View analytics →") below the chart. */
  footer?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <InsightCard overflow="visible" className={cn("p-5", className)}>
      <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
        <div className="min-w-0">
          <p className="text-[15px] font-medium text-foreground">{title}</p>
          {description ? (
            <p className="mt-0.5 text-[12px] text-muted-foreground">{description}</p>
          ) : null}
        </div>
        {action ? <div className="w-full shrink-0 sm:w-auto">{action}</div> : null}
      </div>
      {metrics ? <div className="mt-4">{metrics}</div> : null}
      <div className="mt-4">{children}</div>
      {footer ? <div className="mt-4 border-t border-border/70 pt-3.5">{footer}</div> : null}
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
      <p className="text-sm font-medium text-foreground">{title}</p>
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
      <p className="text-sm font-medium text-foreground">Unable to load analytics</p>
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
  metrics,
  footer,
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
  metrics?: ReactNode;
  footer?: ReactNode;
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
    <ChartCard
      title={title}
      description={description}
      action={action}
      metrics={!isLoading && !isError ? metrics : undefined}
      footer={footer}
      className={className}
    >
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
