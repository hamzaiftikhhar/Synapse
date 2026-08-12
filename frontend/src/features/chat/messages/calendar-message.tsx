"use client";

import { useMemo, useState } from "react";
import {
  addDays,
  eachDayOfInterval,
  endOfMonth,
  format,
  isSameDay,
  startOfMonth,
} from "date-fns";
import type { ChatActionHandler, ChatMessage } from "@/types/chat";
import { cn } from "@/lib/utils";

export function CalendarMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const monthKey = String(message.payload?.month || "");
  const [selected, setSelected] = useState<Date | null>(null);
  const days = useMemo(() => {
    const base = monthKey ? new Date(monthKey) : new Date();
    const start = startOfMonth(base);
    const end = endOfMonth(base);
    return eachDayOfInterval({ start, end });
  }, [monthKey]);
  const labelDate = monthKey ? new Date(monthKey) : new Date();

  return (
    <div className="rounded-[6px] border border-border bg-card p-3">
      <p className="mb-2 text-xs font-medium text-navy">
        {format(labelDate, "MMMM yyyy")}
      </p>
      <div className="grid grid-cols-7 gap-1">
        {days.map((d) => (
          <button
            key={d.toISOString()}
            type="button"
            onClick={() => {
              setSelected(d);
              onAction?.("select_date", format(d, "yyyy-MM-dd"));
            }}
            className={cn(
              "aspect-square rounded-[6px] text-xs",
              selected && isSameDay(selected, d)
                ? "bg-navy text-white"
                : "hover:bg-accent"
            )}
          >
            {format(d, "d")}
          </button>
        ))}
      </div>
      <p className="mt-2 text-[11px] text-muted-foreground">
        Showing next 14 days also works via date picker.
      </p>
      <div className="mt-2 flex flex-wrap gap-1">
        {Array.from({ length: 7 }).map((_, i) => {
          const d = addDays(new Date(), i);
          return (
            <button
              key={i}
              type="button"
              className="rounded-[6px] border border-border px-2 py-1 text-[11px] hover:bg-accent"
              onClick={() => onAction?.("select_date", format(d, "yyyy-MM-dd"))}
            >
              {format(d, "MMM d")}
            </button>
          );
        })}
      </div>
    </div>
  );
}
