"use client";

import { cn } from "@/lib/utils";
import { RobotAvatar } from "@/features/chat/components/robot-avatar";
import { formatMessageTime } from "@/features/chat/components/chat-chrome";
import type { ChatMessage } from "@/types/chat";

export function TextMessage({ message }: { message: ChatMessage }) {
  const isUser = message.role === "user";
  const isSystem = message.role === "system" || message.type === "system";

  if (isSystem) {
    return (
      <div className="flex justify-center py-1">
        <p className="max-w-[95%] rounded-[8px] border border-amber-200/80 bg-amber-50 px-3 py-2 text-center text-xs text-amber-900">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}
    >
      {!isUser ? <RobotAvatar size="sm" className="mt-0.5 shrink-0" /> : null}
      <div className={cn("min-w-0 max-w-[85%]", isUser && "items-end")}>
        <div
          className={cn(
            "px-3.5 py-2.5 text-sm leading-relaxed",
            isUser
              ? "rounded-2xl rounded-br-md bg-white text-foreground shadow-sm ring-1 ring-black/5"
              : "rounded-2xl rounded-bl-md bg-[#ececf0] text-foreground"
          )}
        >
          {message.content}
        </div>
        <p
          className={cn(
            "mt-1 px-1 text-[10px] text-muted-foreground",
            isUser ? "text-right" : "text-left"
          )}
        >
          {formatMessageTime(message.createdAt)}
        </p>
      </div>
    </div>
  );
}
