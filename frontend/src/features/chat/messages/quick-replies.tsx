"use client";

import type { ChatActionHandler, ChatMessage } from "@/types/chat";

export function QuickReplies({
  message,
  onAction,
}: {
  message: ChatMessage;
  onAction?: ChatActionHandler;
}) {
  const replies = (message.payload?.replies as string[]) || [];
  return (
    <div className="flex flex-wrap gap-2">
      {replies.map((r) => (
        <button
          key={r}
          type="button"
          onClick={() => onAction?.("quick_reply", r)}
          className="rounded-[6px] border border-border bg-white px-3 py-1.5 text-xs font-medium text-navy transition-colors hover:border-primary/40 hover:bg-accent"
        >
          {r}
        </button>
      ))}
    </div>
  );
}
