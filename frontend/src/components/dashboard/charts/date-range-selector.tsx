"use client";

import { RANGE_OPTIONS, type AnalyticsRange } from "./colors";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";

export function DateRangeSelector({
  value,
  onChange,
  className,
}: {
  value: AnalyticsRange;
  onChange: (next: AnalyticsRange) => void;
  className?: string;
}) {
  const selected = RANGE_OPTIONS.find((opt) => opt.value === value);

  return (
    <div className={className}>
      <Select
        value={value}
        onValueChange={(v) => v && onChange(v as AnalyticsRange)}
        items={RANGE_OPTIONS}
      >
        <SelectTrigger className="h-8 w-full md:hidden">
          <SelectValue>{selected?.label ?? "Range"}</SelectValue>
        </SelectTrigger>
        <SelectContent>
          {RANGE_OPTIONS.map((opt) => (
            <SelectItem key={opt.value} value={opt.value}>
              {opt.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>

      <Tabs
        value={value}
        onValueChange={(v) => v && onChange(v as AnalyticsRange)}
        className="hidden md:block"
      >
        <TabsList aria-label="Date range" className="flex-wrap">
          {RANGE_OPTIONS.map((opt) => (
            <TabsTrigger key={opt.value} value={opt.value} className="px-2.5 lg:px-3">
              {opt.label}
            </TabsTrigger>
          ))}
        </TabsList>
      </Tabs>
    </div>
  );
}
