"use client";

import { useMemo } from "react";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export type ActivityDay = {
  date: string;
  count: number;
};

const WEEKDAY_LABELS = ["", "Mon", "", "Wed", "", "Fri", ""];

/**
 * Month-grid activity heatmap (GitHub-contributions style) — a companion
 * to the "Conversations & Appointments" line chart, showing the same
 * underlying daily activity as day-of-week/week-over-week density instead
 * of a trend line, so it adds a genuinely different read of the same
 * data rather than a second copy of the line chart.
 */
export function ActivityCalendar({
  days,
  color = "var(--insight-royal)",
  className,
}: {
  days: ActivityDay[];
  color?: string;
  className?: string;
}) {
  const { weeks, max, monthLabel } = useMemo(() => {
    if (days.length === 0) return { weeks: [] as (ActivityDay | null)[][], max: 0, monthLabel: "" };
    const max = Math.max(...days.map((d) => d.count), 1);
    const first = new Date(days[0].date + "T00:00:00");
    const leadingBlanks = first.getDay() === 0 ? 6 : first.getDay() - 1; // Monday-start
    const cells: (ActivityDay | null)[] = [
      ...Array.from({ length: leadingBlanks }, () => null),
      ...days,
    ];
    const weeks: (ActivityDay | null)[][] = [];
    for (let i = 0; i < cells.length; i += 7) weeks.push(cells.slice(i, i + 7));
    const last = new Date(days[days.length - 1].date + "T00:00:00");
    const monthLabel =
      first.getMonth() === last.getMonth()
        ? first.toLocaleDateString("en-US", { month: "long", year: "numeric" })
        : `${first.toLocaleDateString("en-US", { month: "short" })} – ${last.toLocaleDateString("en-US", { month: "short", year: "numeric" })}`;
    return { weeks, max, monthLabel };
  }, [days]);

  if (weeks.length === 0) {
    return (
      <div className={cn("flex h-full items-center justify-center", className)}>
        <p className="text-sm text-muted-foreground">No activity yet</p>
      </div>
    );
  }

  return (
    <div className={cn("flex h-full flex-col", className)}>
      <p className="text-[12px] font-medium text-navy">{monthLabel}</p>
      <div className="mt-3 flex flex-1 gap-[3px]">
        <div className="flex flex-col justify-between py-[1px] pr-1">
          {WEEKDAY_LABELS.map((label, i) => (
            <span key={i} className="text-[9px] leading-none text-muted-foreground">
              {label}
            </span>
          ))}
        </div>
        <div className="flex flex-1 gap-[3px]">
          {weeks.map((week, wi) => (
            <div key={wi} className="flex flex-1 flex-col gap-[3px]">
              {week.map((day, di) => {
                if (!day) return <div key={di} className="flex-1 rounded-[3px]" />;
                const intensity = day.count === 0 ? 0 : Math.max(day.count / max, 0.16);
                return (
                  <Tooltip key={di}>
                    <TooltipTrigger
                      render={
                        <div
                          className="flex-1 rounded-[3px]"
                          style={{
                            background:
                              day.count === 0 ? "var(--insight-wash)" : color,
                            opacity: day.count === 0 ? 1 : intensity,
                          }}
                        />
                      }
                    />
                    <TooltipContent side="top" className="bg-[var(--insight-ink-deep)] px-2.5 py-1.5 text-white">
                      <span className="text-[11px] font-medium">
                        {new Date(day.date + "T00:00:00").toLocaleDateString("en-US", {
                          weekday: "short",
                          month: "short",
                          day: "numeric",
                        })}
                      </span>
                      <span className="ml-1.5 text-[11px] text-white/70">
                        {day.count} {day.count === 1 ? "event" : "events"}
                      </span>
                    </TooltipContent>
                  </Tooltip>
                );
              })}
            </div>
          ))}
        </div>
      </div>
    </div>
  );
}
