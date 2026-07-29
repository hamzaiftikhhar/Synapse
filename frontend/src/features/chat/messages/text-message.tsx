"use client";

import { cn } from "@/lib/utils";
import type { ChatMessage } from "@/types/chat";

export function TextMessage({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  return (
    <div className={cn("flex", isUser ? "justify-end" : "justify-start")}>
      <div
        className={cn(
          "max-w-[85%] rounded-[6px] px-3.5 py-2.5 text-sm leading-relaxed",
          isUser
            ? "bg-navy text-white"
            : "border border-border bg-white text-foreground"
        )}
      >
        {message.content}
      </div>
    </div>
  );
}
