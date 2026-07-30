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
        <p className="max-w-[95%] rounded-[6px] border border-amber-200/80 bg-amber-50 px-3 py-2 text-center text-xs text-amber-900">
          {message.content}
        </p>
      </div>
    );
  }

  return (
    <div
      className={cn("flex gap-2", isUser ? "flex-row-reverse" : "flex-row")}
    >
      {!isUser ? <RobotAvatar size="sm" className="mt-1" /> : null}
      <div className={cn("max-w-[82%]", isUser && "items-end")}>
        <div
          className={cn(
            "px-3.5 py-2.5 text-sm leading-relaxed shadow-sm",
            isUser
              ? "rounded-[12px] rounded-br-[4px] bg-primary text-primary-foreground"
              : "rounded-[12px] rounded-bl-[4px] border border-border bg-white text-foreground"
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
