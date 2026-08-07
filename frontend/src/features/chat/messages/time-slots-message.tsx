"use client";

import { ChatInlineCard } from "@/features/chat/components/chat-inline-card";
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
    <ChatInlineCard className="rounded-[18px] border border-border/80 bg-white p-3 shadow-[0_2px_12px_rgb(11_14_46/0.06)]">
      <p className="mb-2 text-xs font-medium text-muted-foreground">
        Earliest openings
      </p>
      <div className="grid grid-cols-1 gap-2 sm:grid-cols-2">
        {slots.map((s) => (
          <button
            key={s.id}
            type="button"
            onClick={() => onAction?.("select_slot", s)}
            className="rounded-xl border border-border px-3 py-2.5 text-left text-xs font-medium transition-colors hover:border-primary/40 hover:bg-accent"
          >
            <span className="block truncate text-foreground">
              {s.time || s.label}
            </span>
            {s.doctor ? (
              <span className="mt-0.5 block truncate text-[11px] font-normal text-muted-foreground">
                {s.doctor}
              </span>
            ) : null}
          </button>
        ))}
      </div>
    </ChatInlineCard>
  );
}
