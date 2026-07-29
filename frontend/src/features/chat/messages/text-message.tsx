"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types/chat";

export function TextMessage({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system" || message.type === "system";
  return (
    <div
      className={cn(
        "flex",
        isUser ? "justify-end" : "justify-start",
        isSystem && "justify-center"
      )}
    >
      <div
        className={cn(
          "max-w-[85%] rounded-[6px] px-3.5 py-2.5 text-sm leading-relaxed",
          isUser && "bg-navy text-white",
          !isUser &&
            !isSystem &&
            "border border-border bg-white text-foreground",
          isSystem &&
            "max-w-[95%] border border-amber-200/80 bg-amber-50 px-3 py-2 text-center text-xs text-amber-900"
        )}
      >
        {message.content}
      </div>
    </div>
  );
}
