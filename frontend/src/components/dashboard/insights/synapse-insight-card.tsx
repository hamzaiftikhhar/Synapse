"use client";

import Link from "next/link";
import { ArrowRight, Sparkles } from "lucide-react";
import { InsightCard } from "./insight-card";
import { computeSynapseInsight } from "./synapse-insight";
import { cn } from "@/lib/utils";
import type { AnalyticsOverview } from "@/types/api";

export function SynapseInsightCard({
  data,
  isLoading,
  className,
}: {
  data: AnalyticsOverview | undefined;
  isLoading?: boolean;
  className?: string;
}) {
  if (isLoading || !data) {
    return (
      <InsightCard tone="wash" className={cn("p-5", className)}>
        <div className="h-4 w-28 animate-pulse rounded bg-foreground/10" />
        <div className="mt-3 h-3.5 w-full animate-pulse rounded bg-foreground/10" />
        <div className="mt-1.5 h-3.5 w-2/3 animate-pulse rounded bg-foreground/10" />
      </InsightCard>
    );
  }

  const insight = computeSynapseInsight(data);

  return (
    <InsightCard tone="wash" className={cn("p-5", className)}>
      <div className="flex items-center gap-1.5">
        <Sparkles className="size-3.5 text-[var(--insight-royal)]" />
        <p className="text-[12.5px] font-semibold tracking-tight text-[var(--insight-ink-deep)]">
          Synapse insight
        </p>
      </div>
      <p className="mt-2 text-[14px] leading-relaxed text-[var(--insight-ink-deep)]">
        {insight.text}
      </p>
      <Link
        href={insight.href}
        className="mt-3 inline-flex items-center gap-1 text-[12.5px] font-medium text-[var(--insight-royal)] hover:underline"
      >
        {insight.hrefLabel}
        <ArrowRight className="size-3" />
      </Link>
    </InsightCard>
  );
}
