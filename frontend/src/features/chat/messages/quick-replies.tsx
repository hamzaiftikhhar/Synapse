"use client";

import type { ChatActionHandler, ChatMessage } from "@/types/chat";

type QuickReply =
  | string
  | { label: string; message?: string };

export function QuickReplies({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const replies = (message.payload?.replies as QuickReply[]) || [];

  return (
    <div className="flex flex-wrap gap-2">
      {replies.map((reply, i) => {
        const label = typeof reply === "string" ? reply : reply.label;
        const key = typeof reply === "string" ? reply : `${reply.label}-${i}`;

        return (
          <button
            key={key}
            type="button"
            onClick={() => onAction?.("quick_reply", reply)}
            className="rounded-[6px] border border-border bg-card px-3 py-1.5 text-xs font-medium text-navy transition-colors hover:border-primary/40 hover:bg-accent"
          >
            {label}
          </button>
        );
      })}
    </div>
  );
}
