"use client";

import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import { Input } from "@/components/ui/input";
import { cn } from "@/lib/utils";
import type { BusinessHour } from "@/types/api";

export type WeeklyDayValue = {
  day: number; // 0 = Monday .. 6 = Sunday
  isOpen: boolean;
  start: string; // "HH:MM"
  end: string; // "HH:MM"
};

const DAY_LABELS = [
  "Monday",
  "Tuesday",
  "Wednesday",
  "Thursday",
  "Friday",
  "Saturday",
  "Sunday",
];

export function defaultWeeklySchedule(
  overrides?: Partial<Record<number, Partial<WeeklyDayValue>>>
): WeeklyDayValue[] {
  return Array.from({ length: 7 }, (_, day) => ({
    day,
    isOpen: day < 5,
    start: "09:00",
    end: day === 4 ? "15:00" : "17:00",
    ...(overrides?.[day] ?? {}),
  }));
}

/** Convert saved ClinicBusinessHours rows into editor values, falling back
 * to the Mon–Fri 9–5 default for any day that has never been configured
 * (is_closed=false with no times — the API's placeholder for "untouched"). */
export function businessHoursToWeekly(hours: BusinessHour[] | undefined): WeeklyDayValue[] {
  const defaults = defaultWeeklySchedule();
  if (!hours || hours.length === 0) return defaults;
  return defaults.map((fallback) => {
    const row = hours.find((h) => h.day_of_week === fallback.day);
    if (!row) return fallback;
    const untouched = !row.is_closed && !row.open_time && !row.close_time;
    if (untouched) return fallback;
    return {
      day: fallback.day,
      isOpen: !row.is_closed,
      start: row.open_time ? row.open_time.slice(0, 5) : fallback.start,
      end: row.close_time ? row.close_time.slice(0, 5) : fallback.end,
    };
  });
}

export function WeeklyScheduleEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: WeeklyDayValue[];
  onChange: (rows: WeeklyDayValue[]) => void;
  disabled?: boolean;
}) {
  function updateDay(day: number, patch: Partial<WeeklyDayValue>) {
    onChange(value.map((row) => (row.day === day ? { ...row, ...patch } : row)));
  }

  function copyMondayToOthers() {
    const monday = value.find((row) => row.day === 0);
    if (!monday) return;
    onChange(
      value.map((row) =>
        row.day === 0
          ? row
          : { ...row, isOpen: monday.isOpen, start: monday.start, end: monday.end }
      )
    );
  }

  function applyToWeekdays() {
    const monday = value.find((row) => row.day === 0);
    if (!monday) return;
    onChange(
      value.map((row) =>
        row.day >= 1 && row.day <= 4
          ? { ...row, isOpen: monday.isOpen, start: monday.start, end: monday.end }
          : row
      )
    );
  }

  return (
    <div className="space-y-3">
      <div className="flex flex-wrap items-center gap-2">
        <Button type="button" variant="outline" size="sm" onClick={copyMondayToOthers} disabled={disabled}>
          Copy Monday to other days
        </Button>
        <Button type="button" variant="outline" size="sm" onClick={applyToWeekdays} disabled={disabled}>
          Apply to weekdays
        </Button>
      </div>
      <div className="divide-y divide-border overflow-hidden rounded-xl border border-border">
        {value
          .slice()
          .sort((a, b) => a.day - b.day)
          .map((row) => (
            <div
              key={row.day}
              className={cn(
                "flex flex-col gap-2 px-4 py-3 sm:flex-row sm:items-center sm:gap-4",
                !row.isOpen && "bg-muted/30"
              )}
            >
              <label className="flex w-36 shrink-0 items-center gap-2.5 text-sm font-medium">
                <Checkbox
                  checked={row.isOpen}
                  onCheckedChange={(checked) => updateDay(row.day, { isOpen: Boolean(checked) })}
                  disabled={disabled}
                />
                {DAY_LABELS[row.day]}
              </label>
              {row.isOpen ? (
                <div className="flex items-center gap-2">
                  <Input
                    type="time"
                    value={row.start}
                    onChange={(e) => updateDay(row.day, { start: e.target.value })}
                    disabled={disabled}
                    className="w-32"
                    aria-label={`${DAY_LABELS[row.day]} opening time`}
                  />
                  <span className="text-sm text-muted-foreground">to</span>
                  <Input
                    type="time"
                    value={row.end}
                    onChange={(e) => updateDay(row.day, { end: e.target.value })}
                    disabled={disabled}
                    className="w-32"
                    aria-label={`${DAY_LABELS[row.day]} closing time`}
                  />
                </div>
              ) : (
                <p className="text-sm text-muted-foreground">Closed</p>
              )}
            </div>
          ))}
      </div>
    </div>
  );
}
