"use client";

import { useAnalyticsBreakdown } from "@/hooks/api";
import { ChartPanel } from "./chart-card";
import type { AnalyticsRange } from "./colors";
import { RankedBreakdownList } from "./ranked-breakdown-list";

export function BreakdownBarCard({
  dimension,
  title,
  description,
  emptyTitle,
  emptyDescription,
  range = "30d",
  valueLabel = "appointments",
}: {
  dimension: "doctor" | "service" | "specialty" | "insurance";
  title: string;
  description?: string;
  emptyTitle: string;
  emptyDescription: string;
  range?: AnalyticsRange;
  valueLabel?: string;
}) {
  const query = useAnalyticsBreakdown(dimension, range);
  const items = query.data?.items ?? [];
  const more = query.data?.more ?? 0;

  return (
    <ChartPanel
      title={title}
      description={description}
      isLoading={query.isLoading}
      isError={query.isError}
      onRetry={() => void query.refetch()}
      hasData={items.some((row) => row.count > 0)}
      emptyTitle={emptyTitle}
      emptyDescription={emptyDescription}
      action={
        more > 0 ? (
          <span className="text-[12px] text-muted-foreground">+{more} more</span>
        ) : null
      }
    >
      <RankedBreakdownList items={items} valueLabel={valueLabel} />
    </ChartPanel>
  );
}
