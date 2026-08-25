"use client";

import { RANGE_OPTIONS, type AnalyticsRange } from "./colors";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function DateRangeSelector({
  value,
  onChange,
}: {
  value: AnalyticsRange;
  onChange: (next: AnalyticsRange) => void;
}) {
  return (
    <Tabs value={value} onValueChange={(v) => v && onChange(v as AnalyticsRange)}>
      <TabsList aria-label="Date range">
        {RANGE_OPTIONS.map((opt) => (
          <TabsTrigger key={opt.value} value={opt.value} className="px-2.5 sm:px-3">
            {opt.label}
          </TabsTrigger>
        ))}
      </TabsList>
    </Tabs>
  );
}
