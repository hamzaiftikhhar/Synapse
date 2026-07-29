"use client";

import type { ChatActionHandler, ChatMessage, TimeSlotData } from "@/types/chat";

export function TimeSlotsMessage({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const slots = (message.payload?.slots as TimeSlotData[]) || [];
  return (
    <div className="rounded-[6px] border border-border bg-white p-3">
      <p className="mb-2 text-xs font-medium text-navy">Available times</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {slots.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onAction?.("select_slot", s)}
            className="rounded-[6px] border border-border px-2 py-2 text-xs font-medium hover:border-primary/40 hover:bg-accent"
          >
            {s.label}
          </button>
        ))}
      </div>
    </div>
  );
}
